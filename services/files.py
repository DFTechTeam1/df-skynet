from typing import Any, Optional
from urllib.parse import unquote
from fastapi import status
from httpx import Timeout, TimeoutException
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from error import BaseError, DataNotFoundError, DataValidationError
from log import logging
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from config.variables import OVERRIDE_FILE_ROLES
from services.api_caller import APICaller
from services.dto import ConnectionContext
from services.dto.asynced.admin_settings import get_admin_settings
from services.dto.asynced.employees import get_employee
from services.dto.asynced.projects import get_project_task, get_user_tasks
from services.mysql import query
from services.mysql.model import DfEngineGenerationResults, DfEngineUploadFiles
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.mysql.model.entertainment_task_songs import EntertainmentTaskSongs
from services.redis import delete_pattern
from utils import local_time
from services.dto.asynced.files import get_user_uploaded_files
from services.dto.asynced.generation_files import get_generation_main_files
from schemas.payload.setting import AdminGlobalSettingPayload
from services.dto.format_response import FileAction, FolderAction, GenerationAction, TreeFile, TreeFolder

FOLDER_TIMEOUT = Timeout(connect=10, read=60, write=30, pool=10)


def folder_action(depth: int, depth_limit: int) -> FolderAction:
    """`depth` = folders below the project folder (upload=1, upload/images=2, upload/images/x=3...).
    Mirrors Udin: the type root (upload/<type>) is fixed; only subfolders below it can be renamed, deleted or
    moved, and a folder can take another subfolder only while its chain is under the admin `folder_depth_limit`."""
    chain = depth - 2  # subfolder levels below the type root; the root itself is 0
    can_nest = 0 <= chain < depth_limit
    return FolderAction(
        can_create_subfolder=can_nest,
        can_receive_move=can_nest,
        can_rename=chain >= 1,
        can_delete=chain >= 1,
        can_choose_to_move=chain >= 1,
    )


def has_override(roles: Optional[list[str]]) -> bool:
    return bool(roles) and any(role in OVERRIDE_FILE_ROLES for role in roles or [])


def format_file_tree(
    uploaded_files: list[dict[str, Any]],
    generation_files: list[dict[str, Any]],
    user_id: int,
    depth_limit: int,
    can_override: bool = False,
) -> dict[str, Any]:
    """Nest uploaded files into project-folder trees by their storage `path`; only the uploader gets
    rename/delete/move on a file, while folders are open to everyone assigned to the task (their actions come from
    `folder_action` alone). `type=folder` upload rows create (possibly empty) folder nodes carrying their creator/updater.
    Generated files (main versions only) are placed by the storage path recovered from their Udin URL and keep their
    `GenerationAction` (favourite/archive/set-main...)."""
    roots: dict[str, TreeFolder] = {}
    nodes: dict[str, TreeFolder] = {}

    def node(path: str, depth: int) -> TreeFolder:
        if path in nodes:
            return nodes[path]
        folder = TreeFolder(name=path.rsplit("/", 1)[-1], path=path, action=folder_action(depth, depth_limit))
        nodes[path] = folder
        parent, _, _ = path.rpartition("/")
        if depth == 0:
            roots[path] = folder
        else:
            node(parent, depth - 1).children.append(folder)
        return folder

    def place(path: str, tree_file: TreeFile) -> None:
        parts = path.split("/")
        depth = len(parts) - 1 - 3  # folders below `storage/DF-Engine/<project>`
        if depth >= 0:
            node("/".join(parts[:-1]), depth).files.append(tree_file)

    for file in uploaded_files:
        if file["type"] == UploadFileTypes.folder:
            depth = len(file["path"].split("/")) - 3
            if depth >= 0:
                folder = node(file["path"], depth)
                folder.creator = file["creator"]
                folder.updater = file.get("updater")
            continue
        is_owner = (file.get("creator") or {}).get("user_id") == user_id
        place(
            file["path"],
            TreeFile(
                file_uid=file["file_uid"],
                name=file["name"],
                path=file["path"],
                url=file["url"],
                type="upload",
                kind=file["type"],
                icon=file["icon"],
                color=file["color"],
                size=file["size"],
                created_at=file["created_at"],
                creator=file["creator"],
                updater=file.get("updater"),
                action=FileAction.for_upload(is_owner, can_override),
            ),
        )

    for file in generation_files:
        url = file.get("path")
        if not url:
            continue
        path = unquote(url.removeprefix(f"{UDIN_BASE_URL}/"))
        place(
            path,
            TreeFile(
                file_uid=file["file_uid"],
                name=file["name"],
                path=path,
                url=url,
                type="generated",
                kind=file.get("kind") or ("video" if "/videos/" in path else "image"),
                icon=file["icon"],
                color=file["color"],
                size=file["size"],
                created_at=file["created_at"],
                creator=file["creator"],
                updater=file.get("updater"),
                action=GenerationAction.model_validate(file["action"]),
            ),
        )

    return next((folder.model_dump(mode="json") for folder in roots.values()), {})


async def resolve_files(
    ctx: ConnectionContext, source: str, file_uids: list[Any], user_id: int, roles: Optional[list[str]]
) -> tuple[list[Any], dict[str, Any]]:
    """Load `file_uids` from the table `source` names (`generated` -> results, `upload` -> upload files), and
    require each be owned by the caller or the caller hold an `OVERRIDE_FILE_ROLES` role. Returns `(rows, project_task)`;
    all files must share one task/song."""
    uids = [str(uid) for uid in file_uids]
    if source == "upload":
        rows = await query(
            ctx.db,
            DfEngineUploadFiles,
            filters=(
                DfEngineUploadFiles.uid.in_(uids),  # type: ignore
                DfEngineUploadFiles.type != UploadFileTypes.folder,  # type: ignore
            ),
        )
    else:
        rows = await query(
            ctx.db,
            DfEngineGenerationResults,
            options=(selectinload(DfEngineGenerationResults.generation),),  # type: ignore
            filters=(DfEngineGenerationResults.uid.in_(uids),),  # type: ignore
        )
    found = {row.uid: row for row in rows}
    errors = {f"file_uids.{i}": ["file_not_found"] for i, uid in enumerate(uids) if uid not in found}
    if errors:
        raise DataNotFoundError(message="file_not_found", error=errors)

    can_override = has_override(roles)
    errors = {
        f"file_uids.{i}": ["file_action_not_permitted"]
        for i, uid in enumerate(uids)
        if not can_override and found[uid].created_by != user_id
    }
    if errors:
        raise DataValidationError(message="file_action_not_permitted", error=errors)

    scopes = {
        (row.task_id, row.song_id) if source == "upload" else (row.generation.task_id, row.generation.song_id)
        for row in found.values()
    }
    if len(scopes) != 1:
        raise DataValidationError(message="file_not_found", error={"file_uids": ["file_not_found"]})
    task_id, song_id = scopes.pop()
    project_task = await get_project_task(ctx, task_id=task_id, song_id=song_id)
    return [found[uid] for uid in uids], project_task


async def get_folder_depth_limit(ctx: ConnectionContext) -> int:
    admin_setting = await get_admin_settings(ctx)
    return (
        admin_setting.get("folder_depth_limit") or AdminGlobalSettingPayload.model_fields["folder_depth_limit"].default
    )


def folder_scope(path: str) -> tuple[str, ...]:
    """`(upload|generated, images|videos)` of a `storage/DF-Engine/<project>/...` path; shorter for the project folder
    and the `upload`/`generated` folders."""
    return tuple(path.split("/")[3:5])


async def ensure_task_assigned(ctx: ConnectionContext, project_task: dict[str, Any], user_id: int) -> None:
    """Only users assigned to the task (`project_task_pics`) or song (`entertainment_task_songs`) may change folders."""
    employee = await get_employee(ctx, user_id=user_id)
    if not project_task["is_song"]:
        await get_user_tasks(ctx, project_task["id"], employee["id"])  # raises employee_not_assigned_task
        return
    assignment = await query(
        ctx.db,
        EntertainmentTaskSongs,
        filters=(
            EntertainmentTaskSongs.project_song_list_id == project_task["id"],
            EntertainmentTaskSongs.employee_id == employee["id"],
        ),
        fetch_one=True,
    )
    if assignment is None:
        raise DataNotFoundError(message="employee_not_assigned_task")


async def call_udin_folder(
    method: str, operation: str, project_uid: str, user_id: int, body: dict[str, Any], failed_message: str, tag: str
) -> Any:
    """One Udin folder call: 504 on timeout, Udin's error surfaced under `failed_message`, `data` returned on success."""
    try:
        async with APICaller(
            base_url=UDIN_BASE_URL, headers={"X-API-Key": UDIN_API_KEY}, timeout=FOLDER_TIMEOUT
        ) as caller:  # type: ignore
            upstream = await caller.udin(
                method, f"/engine/storage/{operation}/{project_uid}", user_id=user_id, json=body
            )  # type: ignore
    except TimeoutException:
        logging.error(f"[{tag}] user={user_id} udin timed out")
        raise BaseError(status_code=status.HTTP_504_GATEWAY_TIMEOUT, message="upload_timeout")
    try:
        data: dict[str, Any] = upstream.json() if upstream.content else {}
    except ValueError:
        data = {}
    if upstream.is_error:
        logging.warning(f"[{tag}] user={user_id} udin rejected status={upstream.status_code} body={data}")
        error = data.get("error") or ({"path": [data["message"]]} if data.get("message") else None)
        if error and failed_message == "folders_move_failed":
            error = {k.replace("sources.", "folder_paths.", 1): v for k, v in error.items()}
        detail = next((v[0] for v in error.values() if v), None) if error else None
        raise BaseError(status_code=upstream.status_code, message=detail or failed_message, error=error)
    return data.get("data")


async def delete_upload_files_under(ctx: ConnectionContext, project_uid: str, user_id: int, path: str) -> None:
    """Permanently delete (Udin + DB) every uploaded file under the `upload` folder `path`."""
    rows = await query(
        ctx.db,
        DfEngineUploadFiles,
        filters=(
            DfEngineUploadFiles.type != UploadFileTypes.folder,  # type: ignore
            DfEngineUploadFiles.path.startswith(path + "/", autoescape=True),  # type: ignore
        ),
    )
    if not rows:
        return
    await call_udin_folder(
        "DELETE",
        "delete-files",
        project_uid,
        user_id,
        {"sources": [r.path for r in rows]},
        "files_delete_failed",
        "delete-files",
    )
    for row in rows:
        await ctx.redis.delete(ctx.key.user_file_detail(row.uid))  # type: ignore
        await ctx.db.delete(row)
    await ctx.db.flush()


def task_scope(project_task: dict[str, Any]) -> tuple[Optional[int], Optional[int]]:
    """`(task_id, song_id)` of a resolved project task or song: exactly one is set."""
    return (None, project_task["id"]) if project_task["is_song"] else (project_task["id"], None)


async def invalidate_generation_lists(ctx: ConnectionContext, user_ids: Any) -> None:
    """Drop the cached result/archived/favourited lists of these viewers (all tasks). The lists are keyed per viewer, so
    a change made by an override user must also clear the file owners' (and a previous updater's) lists."""
    for uid in {uid for uid in user_ids if uid is not None}:
        for pattern in ctx.key.generation_files_user_lists_patterns(uid):
            await delete_pattern(ctx.redis, pattern)


async def apply_folder_changes(
    ctx: ConnectionContext,
    project_task: dict[str, Any],
    user_id: int,
    pairs: Optional[list[dict[str, Any]]] = None,
    moves: Optional[list[tuple[str, str]]] = None,
    deleted: Optional[list[str]] = None,
) -> None:
    """Mirror a Udin folder operation into the DB, then invalidate every cache `build_file_tree` (and the file
    caches that embed paths) reads. `pairs` are Udin's `{from, to}` file moves (matched by path, across all tasks of
    the project, in `DfEngineUploadFiles` and `DfEngineGenerationResults`); `moves` are `(old, new)` folder prefixes
    to rewrite on `type=folder` rows; `deleted` are folder prefixes whose rows are removed. Called with no arguments
    after a create, it only invalidates."""
    pairs, moves, deleted = pairs or [], moves or [], deleted or []
    is_song = project_task["is_song"]
    now = local_time()
    scopes = {(None if is_song else project_task["id"], project_task["id"] if is_song else None)}
    generation_task_ids = {project_task["id"]}
    creators: set[Optional[int]] = {user_id}
    upload_uids: set[str] = set()
    result_uids: set[str] = set()
    to_by_from = {pair["from"]["path"]: pair["to"] for pair in pairs}

    if to_by_from:
        uploads = await query(
            ctx.db,
            DfEngineUploadFiles,
            filters=(
                DfEngineUploadFiles.path.in_(list(to_by_from)),  # type: ignore
                DfEngineUploadFiles.type != UploadFileTypes.folder,  # type: ignore
            ),
        )
        for row in uploads:
            to = to_by_from[row.path]
            row.path, row.name, row.updated_by, row.updated_at = to["path"], to["name"], user_id, now
            scopes.add((row.task_id, row.song_id))
            creators.add(row.created_by)
            upload_uids.add(row.uid)
            ctx.db.add(row)
        results = await query(
            ctx.db,
            DfEngineGenerationResults,
            options=(selectinload(DfEngineGenerationResults.generation),),  # type: ignore
            filters=(DfEngineGenerationResults.path.in_(list(to_by_from)),),  # type: ignore
        )
        for row in results:
            to = to_by_from[row.path]
            row.path, row.name, row.updated_by, row.updated_at = to["path"], to["name"], user_id, now
            if row.generation and row.generation.task_id:
                generation_task_ids.add(row.generation.task_id)
            creators.add(row.created_by)
            result_uids.add(row.uid)
            ctx.db.add(row)

    async def folder_rows(prefix: str) -> Any:
        return await query(
            ctx.db,
            DfEngineUploadFiles,
            filters=(
                DfEngineUploadFiles.type == UploadFileTypes.folder,  # type: ignore
                or_(
                    DfEngineUploadFiles.path == prefix,  # type: ignore
                    DfEngineUploadFiles.path.startswith(prefix + "/", autoescape=True),  # type: ignore
                ),
            ),
        )

    for old, new in moves:
        for row in await folder_rows(old):
            row.path = new + row.path[len(old) :]
            row.name = row.path.rsplit("/", 1)[-1]
            row.updated_by, row.updated_at = user_id, now
            scopes.add((row.task_id, row.song_id))
            creators.add(row.created_by)
            upload_uids.add(row.uid)
            ctx.db.add(row)
    for path in deleted:
        for row in await folder_rows(path):
            scopes.add((row.task_id, row.song_id))
            creators.add(row.created_by)
            upload_uids.add(row.uid)
            await ctx.db.delete(row)
    await ctx.db.flush()

    creators.discard(None)
    for task_id, song_id in scopes:
        await delete_pattern(ctx.redis, ctx.key.user_files_pattern(task_id=task_id, song_id=song_id))
    for task_id in generation_task_ids:
        await delete_pattern(ctx.redis, ctx.key.generation_files_main_list_pattern(task_id))
    for uid in creators:
        await delete_pattern(ctx.redis, ctx.key.generation_files_references_picker_pattern(uid))  # type: ignore
    if pairs or moves or deleted:  # paths changed: details and per-user lists embed them
        for uid in upload_uids:
            await ctx.redis.delete(ctx.key.user_file_detail(uid))  # type: ignore
        for uid in result_uids:
            await ctx.redis.delete(ctx.key.generation_files_main_detail(uid))  # type: ignore
            await ctx.redis.delete(ctx.key.generation_files_variant_detail(uid))  # type: ignore
            await ctx.redis.delete(ctx.key.generation_files_variants_detail(uid))  # type: ignore
        for uid in creators:
            for pattern in ctx.key.generation_files_user_lists_patterns(uid):
                await delete_pattern(ctx.redis, pattern)
            await delete_pattern(ctx.redis, ctx.key.generation_file_detail_pattern(uid))  # type: ignore
    logging.info(
        f"[folder-changes] user={user_id} project_id={project_task['project_id']} pairs={len(pairs)} "
        f"moves={len(moves)} deleted={len(deleted)} scopes={len(scopes)}"
    )


async def build_file_tree(
    ctx: ConnectionContext,
    project_task: dict[str, Any],
    user_id: int,
    my_task: bool = False,
    roles: Optional[list[str]] = None,
) -> dict[str, Any]:
    """The `GET /files/{task_uid}` payload. Each source is cached by its own getter (uploads, generations,
    admin settings), so after an invalidation this repopulates only what was cleared."""
    is_song = project_task["is_song"]
    uploaded = await get_user_uploaded_files(
        ctx,
        task_id=None if is_song else project_task["id"],
        song_id=project_task["id"] if is_song else None,
        user_id=user_id if my_task else None,
    )
    task_id, song_id = task_scope(project_task)
    generated = await get_generation_main_files(ctx, user_id, task_id, my_task, None, has_override(roles), song_id)
    tree = format_file_tree(uploaded, generated, user_id, await get_folder_depth_limit(ctx), has_override(roles))
    logging.info(
        f"[file-tree] user={user_id} {'song_id' if is_song else 'task_id'}={project_task['id']} "
        f"uploaded={len(uploaded)} generated={len(generated)} root={tree.get('path')}"
    )
    return tree


def find_folder(node: dict[str, Any], target: str) -> Optional[dict[str, Any]]:
    if node.get("path") == target:
        return node
    for child in node.get("children") or []:
        if found := find_folder(child, target):
            return found
    return None
