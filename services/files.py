from typing import Any, Optional
from urllib.parse import unquote
from log import logging
from apps.secret import UDIN_BASE_URL
from services.dto import ConnectionContext
from services.dto.asynced.admin_settings import get_admin_settings
from services.dto.asynced.files import get_user_uploaded_files
from services.dto.asynced.generation_files import get_generation_main_files
from schemas.payload.setting import AdminGlobalSettingPayload
from services.dto.format_response import FileAction, FolderAction, GenerationAction, TreeFile, TreeFolder


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


def format_file_tree(
    uploaded_files: list[dict[str, Any]], generation_files: list[dict[str, Any]], user_id: int, depth_limit: int
) -> dict[str, Any]:
    """Nest uploaded files into project-folder trees by their storage `path`; only the uploader gets
    rename/delete/move on a file, and a subfolder is only actionable when all files under it are the caller's. Generated files (main versions only) are placed by the storage path recovered
    from their Udin URL and keep their `GenerationAction` (favourite/archive/set-main...)."""
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

    foreign: set[str] = set()  # folders that directly hold a file of another user

    def place(path: str, tree_file: TreeFile, is_owner: bool) -> None:
        parts = path.split("/")
        depth = len(parts) - 1 - 3  # folders below `storage/DF-Engine/<project>`
        if depth >= 0:
            folder_path = "/".join(parts[:-1])
            node(folder_path, depth).files.append(tree_file)
            if not is_owner:
                foreign.add(folder_path)

    for file in uploaded_files:
        is_owner = (file.get("creator") or {}).get("user_id") == user_id
        place(
            file["path"],
            TreeFile(
                file_uid=file["file_uid"],
                name=file["name"],
                path=file["path"],
                url=file["url"],
                kind=file["type"],
                icon=file["icon"],
                color=file["color"],
                size=file["size"],
                created_at=file["created_at"],
                creator=file["creator"],
                action=FileAction(can_rename=is_owner, can_delete=is_owner, can_choose_to_move=is_owner),
            ),
            is_owner,
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
                kind=file.get("kind") or ("video" if "/videos/" in path else "image"),
                icon=file["icon"],
                color=file["color"],
                size=file["size"],
                created_at=file["created_at"],
                creator=file["creator"],
                action=GenerationAction.model_validate(file["action"]),
            ),
            (file.get("creator") or {}).get("user_id") == user_id,
        )

    def guard(folder: TreeFolder, depth: int) -> bool:
        """True if every file under `folder` is the caller's. A subfolder holding anyone else's file loses all
        its actions; the type root (upload/<type>, depth 2) is shared by everyone and keeps its rule-based ones."""
        owned = folder.path not in foreign
        for child in folder.children:
            owned = guard(child, depth + 1) and owned
        if depth - 2 >= 1 and not owned:
            folder.action = FolderAction()
        return owned

    for root in roots.values():
        guard(root, 0)

    return next((folder.model_dump(mode="json") for folder in roots.values()), {})


async def build_file_tree(
    ctx: ConnectionContext, project_task: dict[str, Any], user_id: int, my_task: bool = False
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
    generated = await get_generation_main_files(ctx, user_id, project_task["id"], user_id, None)
    admin_setting = await get_admin_settings(ctx)
    # unsaved admin settings carry no key, so fall back to the payload default
    depth_limit = (
        admin_setting.get("folder_depth_limit") or AdminGlobalSettingPayload.model_fields["folder_depth_limit"].default
    )
    tree = format_file_tree(uploaded, generated, user_id, depth_limit)
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
