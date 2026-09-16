import json
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Coroutine, Optional
from urllib.parse import unquote
from uuid import UUID
from fastapi import status
from redis.asyncio import Redis
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from error import BaseError, DataNotFoundError, DataValidationError
from log import logging
from services.api_caller import APICaller
from services.mysql import query
from services.mysql.model import (
    DfEngineExternalApiCalls,
    DfEngineModelOptions,
    DfEngineSettings,
    Users,
    Employees,
    ProjectTasks,
)
from services.mysql.model.df_engine_upload_files import DfEngineUploadFiles, UploadFileTypes
from services.mysql.model.df_engine_generations import DfEngineGenerations
from services.mysql.model.df_engine_generation_results import DfEngineGenerationResults
from services.redis import CacheKeys, delete_pattern, get_json, set_json
from utils.serializer import serialize
from utils.formatter import format_udin_url, format_user_employees, format_size, format_idr
from utils import local_time
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL

DEFAULT_FOLDER_DEPTH_LIMIT = 4
USD_TO_IDR_RATE = Decimal("16000")


@dataclass
class FileCtx:
    db: AsyncSession
    redis: Redis
    project_task: dict[str, Any]
    user_id: int


@dataclass
class UdinRequest:
    method: str
    path: str
    json: dict[str, Any]
    error_message: str


@dataclass
class UdinLog:
    method: str
    endpoint: str
    request_payload: dict[str, Any] | None
    status_code: int | None
    response_headers: dict[str, Any] | None
    response_body: dict[str, Any] | None
    error_message: str | None
    start: float


@dataclass
class FieldMutation:
    field: str
    value: Any
    is_valid_state: Callable[[DfEngineGenerationResults], bool]
    invalid_state_message: str


class FilesService:
    async def get_project_task(self, db: AsyncSession, uid: UUID) -> dict[str, Any]:
        project_task = await query(
            db=db,
            table=ProjectTasks,
            filters=(ProjectTasks.uid == str(uid),),
            options=(selectinload(ProjectTasks.project),),  # type: ignore
            fetch_one=True,
        )
        project_task = serialize(project_task)
        if not project_task:
            raise DataNotFoundError(message="project_task_not_found")

        # Note: Validation will be enabled later
        # if project_task['status'] == 4:
        #     raise DataValidationError(message="task_already_finished")

        # if project_task['project']['status'] != 6:
        #     raise DataValidationError(message="project_not_ongoing")

        return project_task

    async def fetch_generation_results(self, ctx: FileCtx, archived: bool = False) -> list[dict[str, Any]]:
        archived_filter = (
            DfEngineGenerationResults.archieved_at.is_not(None)  # type: ignore
            if archived
            else DfEngineGenerationResults.archieved_at.is_(None)  # type: ignore
        )
        rows = serialize(
            await query(
                db=ctx.db,
                table=DfEngineGenerationResults,
                joins=((DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
                options=self.creator_updater_loaders(DfEngineGenerationResults),
                filters=(
                    DfEngineGenerations.task_id == ctx.project_task["id"],
                    DfEngineGenerations.created_by == ctx.user_id,
                    archived_filter,
                ),
            )
        )
        return await self.attach_generation_meta(ctx, rows)

    async def fetch_favourited_results(self, ctx: FileCtx) -> list[dict[str, Any]]:
        rows = serialize(
            await query(
                db=ctx.db,
                table=DfEngineGenerationResults,
                joins=((DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
                options=self.creator_updater_loaders(DfEngineGenerationResults),
                filters=(
                    DfEngineGenerations.task_id == ctx.project_task["id"],
                    DfEngineGenerations.created_by == ctx.user_id,
                    DfEngineGenerationResults.is_favourite.is_(True),  # type: ignore
                ),
            )
        )
        return await self.attach_generation_meta(ctx, rows)

    async def attach_generation_meta(self, ctx: FileCtx, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge kind/prompt/cost/model from DfEngineGenerations (+ its model_option) onto each
        file's "generation" key via a plain columns= query - only these fields are needed, so
        there's no reason to fetch/serialize full ORM rows (which would also eager-load the
        unrelated api_key/api_key_snapshot polymorphic relationships for nothing)."""
        generation_ids = {f["generation_id"] for f in files if f.get("generation_id")}
        if not generation_ids:
            return files
        rows = await query(
            db=ctx.db,
            table=DfEngineGenerations,
            columns=(
                DfEngineGenerations.id,
                DfEngineGenerations.kind,
                DfEngineGenerations.prompt,
                DfEngineGenerations.cost,
                DfEngineModelOptions.name,
            ),
            joins=((DfEngineModelOptions, DfEngineGenerations.model_id == DfEngineModelOptions.id),),
            filters=(DfEngineGenerations.id.in_(generation_ids),),  # type: ignore
        )
        meta = {row.id: {"kind": row.kind, "prompt": row.prompt, "cost": row.cost, "model": row.name} for row in rows}
        for file in files:
            file["generation"] = meta.get(file.get("generation_id"))
        return files

    async def get_archived_files(self, ctx: FileCtx, file_type: Optional[str] = None) -> list[dict[str, Any]]:
        """Cache-first flat (one-level) list of this user's archived generation results, optionally
        filtered to `file_type` ("image"/"video"). The cache holds the full list; filtering happens
        after the cache read so `image`/`video`/unfiltered all share one cache key."""
        cache_key = CacheKeys().user_archived_files(ctx.user_id, ctx.project_task["id"])
        files = await get_json(ctx.redis, cache_key)
        if files is None:
            files = await self.refresh_archived_files(ctx)
        return [f for f in files if f["type"] == file_type] if file_type else files

    async def get_favourited_files(self, ctx: FileCtx, file_type: Optional[str] = None) -> list[dict[str, Any]]:
        """Cache-first flat (one-level) list of this user's favourited generation results, optionally
        filtered to `file_type` ("image"/"video")."""
        cache_key = CacheKeys().user_favourited_files(ctx.user_id, ctx.project_task["id"])
        files = await get_json(ctx.redis, cache_key)
        if files is None:
            files = await self.refresh_favourited_files(ctx)
        return [f for f in files if f["type"] == file_type] if file_type else files

    async def refresh_archived_files(self, ctx: FileCtx) -> list[dict[str, Any]]:
        """Recompute + re-cache the archived list inline, so the next GET is a cache hit."""
        rows = await self.fetch_generation_results(ctx, archived=True)
        files = self.build_flat_file_list(rows, ctx.user_id)
        await set_json(ctx.redis, CacheKeys().user_archived_files(ctx.user_id, ctx.project_task["id"]), files)
        return files

    async def refresh_favourited_files(self, ctx: FileCtx) -> list[dict[str, Any]]:
        """Recompute + re-cache the favourited list inline, so the next GET is a cache hit."""
        rows = await self.fetch_favourited_results(ctx)
        files = self.build_flat_file_list(rows, ctx.user_id)
        await set_json(ctx.redis, CacheKeys().user_favourited_files(ctx.user_id, ctx.project_task["id"]), files)
        return files

    async def fetch_file_tree(self, ctx: FileCtx) -> list[dict[str, Any]]:
        """Live file tree only: uploads + non-archived generation results. Archived/favourited
        generation results are browsed as flat lists via `get_archived_files`/`get_favourited_files`."""
        generated_files = await self.fetch_generation_results(ctx)
        task_files = serialize(
            await query(
                db=ctx.db,
                table=DfEngineUploadFiles,
                options=self.creator_updater_loaders(DfEngineUploadFiles),
                filters=(
                    DfEngineUploadFiles.task_id == ctx.project_task["id"],
                    DfEngineUploadFiles.created_by == ctx.user_id,
                ),
            )
        )
        return self.build_file_tree(task_files + generated_files, ctx.user_id)

    def creator_updater_loaders(self, model: type[Any]) -> tuple[Any, ...]:
        """Eager-load `created_by_user`/`updated_by_user` -> `employees`, for `format_user_employees`."""
        return tuple(
            selectinload(getattr(model, relation))  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname)  # type: ignore
            for relation in ("created_by_user", "updated_by_user")
        )

    async def folder_depth_limit(self, db: AsyncSession) -> int:
        """Deepest a subfolder chain may nest under a type root, per the admin-configurable
        `folder_depth_limit` setting. Falls back to DEFAULT_FOLDER_DEPTH_LIMIT if unset."""
        row = await query(
            db=db,
            table=DfEngineSettings,
            filters=(DfEngineSettings.code == "admin_setting", DfEngineSettings.key == "folder_depth_limit"),
            fetch_one=True,
        )
        return json.loads(row.value) if row and row.value else DEFAULT_FOLDER_DEPTH_LIMIT

    def base_of(self, path: str) -> str:
        """Strip everything from `/upload/` or `/generated/` onward, mirroring `build_file_tree`."""
        for segment in ("upload", "generated"):
            marker = f"/{segment}/"
            if marker in path:
                return path.split(marker)[0]
        return path

    def type_root_of(self, path: str) -> str | None:
        """Return the `<base>/<upload|generated>/<images|videos>` root that `path` sits under/at, or None."""
        base_path = self.base_of(path)
        for segment in ("upload", "generated"):
            for kind in ("images", "videos"):
                root = f"{base_path}/{segment}/{kind}"
                if path == root or path.startswith(f"{root}/"):
                    return root
        return None

    def relative_depth(self, path: str) -> int | None:
        """Depth of `path` below its type root (0 = the type root itself), or None if `path` isn't in scope."""
        type_root = self.type_root_of(path)
        if type_root is None:
            return None
        relative = path[len(type_root) :].strip("/")
        return 0 if not relative else len(relative.split("/"))

    def subtree_depth(self, folder_node: dict[str, Any]) -> int:
        """0 if `folder_node` has no nested subfolders, else 1 + its deepest child subtree."""
        childs = folder_node["childs"]
        return 0 if not childs else 1 + max(self.subtree_depth(c) for c in childs)

    async def sync_paths(self, db: AsyncSession, pairs: list[dict[str, Any]], task_id: int, user_id: int) -> None:
        """Update DfEngineUploadFiles.path/name for every {from, to} pair udin reports moved/renamed.
        Silently skips pairs with no matching row (generated/dummy entries aren't backed by real rows yet)."""
        if not pairs:
            return
        rows = await query(
            db=db,
            table=DfEngineUploadFiles,
            filters=(
                DfEngineUploadFiles.task_id == task_id,
                DfEngineUploadFiles.created_by == user_id,
                DfEngineUploadFiles.path.in_([pair["from"]["path"] for pair in pairs]),  # type: ignore
            ),
        )
        by_old_path = {row.path: row for row in rows}
        for pair in pairs:
            row = by_old_path.get(pair["from"]["path"])
            if row is None:
                continue
            row.path = pair["to"]["path"]
            row.name = pair["to"]["name"]
            db.add(row)
        await db.flush()

    async def rewrite_folder_prefix(
        self, db: AsyncSession, old_path: str, new_path: str, task_id: int, user_id: int
    ) -> None:
        """Rewrite type=folder rows at/under `old_path` to `new_path` after a rename/move.
        Unlike files, a folder's own row never appears in udin's {from, to} pairs (it has
        no file), so it needs its path rewritten by prefix instead of `sync_paths`."""
        rows = await query(
            db=db,
            table=DfEngineUploadFiles,
            filters=(
                DfEngineUploadFiles.task_id == task_id,
                DfEngineUploadFiles.created_by == user_id,
                DfEngineUploadFiles.type == UploadFileTypes.folder,
            ),
        )
        for row in rows:
            if row.path == old_path:
                row.path, row.name = new_path, new_path.rsplit("/", 1)[-1]
            elif row.path.startswith(f"{old_path}/"):
                row.path = new_path + row.path[len(old_path) :]
            else:
                continue
            db.add(row)
        await db.flush()

    async def delete_paths(self, db: AsyncSession, paths: list[str], task_id: int, user_id: int) -> None:
        """Delete DfEngineUploadFiles rows matching `paths` udin has already removed from disk."""
        if not paths:
            return
        rows = await query(
            db=db,
            table=DfEngineUploadFiles,
            filters=(
                DfEngineUploadFiles.task_id == task_id,
                DfEngineUploadFiles.created_by == user_id,
                DfEngineUploadFiles.path.in_(paths),  # type: ignore
            ),
        )
        for row in rows:
            await db.delete(row)
        await db.flush()

    async def get_tree(self, ctx: FileCtx) -> list[dict[str, Any]]:
        """Cache-first file tree fetch, shared by every mutation endpoint before it mutates the tree."""
        cache_key = CacheKeys().user_files(ctx.user_id, ctx.project_task["id"])
        file_tree = await get_json(ctx.redis, cache_key)
        if file_tree is None:
            file_tree = await self.fetch_file_tree(ctx)
            await set_json(ctx.redis, cache_key, file_tree)
        return file_tree

    async def invalidate_and_refresh(self, ctx: FileCtx) -> list[dict[str, Any]]:
        """Drop every cached tree/detail key for this task+user, then rebuild and re-cache the tree."""
        await delete_pattern(ctx.redis, f"user_files:task={ctx.project_task['id']}:user_id={ctx.user_id}*")
        await delete_pattern(ctx.redis, CacheKeys().references_picker_pattern(ctx.user_id))
        file_tree = await self.fetch_file_tree(ctx)
        await set_json(ctx.redis, CacheKeys().user_files(ctx.user_id, ctx.project_task["id"]), file_tree)
        return file_tree

    async def get_folder_detail(self, ctx: FileCtx, folder_path: str) -> dict[str, Any]:
        """Cache-first single-folder lookup, falling back to the full tree on a cache miss."""
        detail_key = CacheKeys().user_folder_detail(ctx.user_id, ctx.project_task["id"], folder_path)
        folder = await get_json(ctx.redis, detail_key)
        if folder is None:
            tree = await self.get_tree(ctx)
            folder = self.find_folder(tree, folder_path)
            if folder is None:
                raise DataNotFoundError(message="folder_not_found")
            await set_json(ctx.redis, detail_key, folder)
        return folder

    async def get_file_detail(self, ctx: FileCtx, file_uid: str, kind: str = "upload") -> dict[str, Any]:
        """Cache-first single-file lookup. `kind="upload"` looks up one uploaded file by uid
        directly in `df_engine_upload_files` (folders excluded - they have no file detail of
        their own). `kind="generated"` looks up one generation result by uid directly,
        regardless of its archived/favourite state. Either way, a uid that doesn't match a row
        of the requested kind is a 404 - it never falls back to the other table."""
        detail_key = CacheKeys().user_file_detail(ctx.user_id, ctx.project_task["id"], file_uid, kind)
        file = await get_json(ctx.redis, detail_key)
        if file is not None:
            return file

        if kind == "generated":
            file = await self.generated_file_detail(ctx, file_uid)
        else:
            row = await query(
                db=ctx.db,
                table=DfEngineUploadFiles,
                options=self.creator_updater_loaders(DfEngineUploadFiles),
                filters=(
                    DfEngineUploadFiles.uid == file_uid,
                    DfEngineUploadFiles.task_id == ctx.project_task["id"],
                    DfEngineUploadFiles.created_by == ctx.user_id,
                    DfEngineUploadFiles.type != UploadFileTypes.folder,
                ),
                fetch_one=True,
            )
            file = self.file_entry(serialize(row), ctx.user_id) if row else None

        if file is None:
            raise DataNotFoundError(message="file_not_found")
        await set_json(ctx.redis, detail_key, file)
        return file

    async def generated_file_detail(self, ctx: FileCtx, file_uid: str) -> Optional[dict[str, Any]]:
        """One generation result. `variants` (the rest of its root+children family, 1 level) is
        attached only when the fetched result is currently `is_main` - a non-main result returns
        just its own data, mirroring build_file_tree's is_main-based grouping."""
        row = await query(
            db=ctx.db,
            table=DfEngineGenerationResults,
            joins=((DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
            options=self.creator_updater_loaders(DfEngineGenerationResults),
            filters=(
                DfEngineGenerationResults.uid == file_uid,
                DfEngineGenerations.task_id == ctx.project_task["id"],
                DfEngineGenerations.created_by == ctx.user_id,
            ),
            fetch_one=True,
        )
        if row is None:
            return None
        target = (await self.attach_generation_meta(ctx, [serialize(row)]))[0]
        entry = self.file_entry(target, ctx.user_id)
        if not target["is_main"]:
            return entry

        root_id = target["parent_id"] if target["parent_id"] is not None else target["id"]
        family = serialize(
            await query(
                db=ctx.db,
                table=DfEngineGenerationResults,
                joins=((DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
                options=self.creator_updater_loaders(DfEngineGenerationResults),
                filters=(
                    or_(DfEngineGenerationResults.id == root_id, DfEngineGenerationResults.parent_id == root_id),
                    DfEngineGenerations.task_id == ctx.project_task["id"],
                    DfEngineGenerations.created_by == ctx.user_id,
                ),
            )
        )
        family = await self.attach_generation_meta(ctx, family)
        entries = {row["uid"]: self.file_entry(row, ctx.user_id) for row in family}
        entries.pop(file_uid, None)
        entry["variants"] = list(entries.values())
        return entry

    async def employee_nickname(self, db: AsyncSession, user_id: int) -> Optional[str]:
        user = await query(
            db=db,
            table=Users,
            options=(selectinload(Users.employees).load_only(Employees.nickname),),  # type: ignore
            filters=(Users.id == user_id,),
            fetch_one=True,
        )
        return user.employees.nickname if user and user.employees else None

    async def call_udin(self, ctx: FileCtx, request: UdinRequest) -> dict[str, Any]:
        """Proxy one mutation call to udin, raising `BaseError` with `request.error_message` on any
        non-2xx response. Every call (success or failure) is logged to df_engine_external_api_calls
        as type="udin"."""
        start = time.perf_counter()
        status_code, endpoint, response_headers, body, error_message = None, request.path, None, {}, None
        try:
            async with APICaller(base_url=UDIN_BASE_URL, headers={"X-API-Key": UDIN_API_KEY}) as caller:
                upstream = await caller.call(request.method, request.path, json=request.json, raise_for_status=False)  # type: ignore
            status_code = upstream.status_code
            endpoint = str(upstream.request.url)
            response_headers = dict(upstream.headers)
            try:
                body: dict[str, Any] = upstream.json() if upstream.content else {}
            except ValueError:
                body = {}
            if status_code >= status.HTTP_400_BAD_REQUEST:
                error_message = request.error_message
                # udin often reports the actual reason in "message" rather than a structured "error" - surface it too.
                error = body.get("error") or ({"detail": [body["message"]]} if body.get("message") else None)
                raise BaseError(status_code=status_code, message=request.error_message, error=error)
            return body
        finally:
            await self.log_udin_call(
                ctx,
                UdinLog(
                    method=request.method,
                    endpoint=endpoint,
                    request_payload=request.json,
                    status_code=status_code,
                    response_headers=response_headers,
                    response_body=body,
                    error_message=error_message,
                    start=start,
                ),
            )

    async def log_udin_call(self, ctx: FileCtx, log: UdinLog) -> None:
        try:
            name = await self.employee_nickname(ctx.db, ctx.user_id)
            ctx.db.add(
                DfEngineExternalApiCalls(
                    name=name,
                    type="udin",
                    method=log.method,
                    endpoint=log.endpoint,
                    request_payload=log.request_payload,
                    response_status_code=log.status_code,
                    response_headers=log.response_headers,
                    response_body=log.response_body,
                    error_message=log.error_message,
                    duration_ms=int((time.perf_counter() - log.start) * 1000),
                )
            )
            await ctx.db.flush()
        except Exception:
            logging.error(f"[{log.endpoint}] failed to write udin call log\n{traceback.format_exc()}")

    async def sync_after(self, endpoint: str, uid: UUID, coro: Coroutine[Any, Any, None]) -> None:
        """Run a post-udin-success DB sync; log and swallow failures since the real mutation already completed."""
        try:
            await coro
        except Exception:
            logging.error(f"[{endpoint}] uid={uid} db-sync failed after udin success\n{traceback.format_exc()}")

    async def create_folder(self, ctx: FileCtx, current_path: str, name: str) -> list[dict[str, Any]]:
        tree = await self.get_tree(ctx)
        parent = self.find_folder(tree, current_path)
        if parent is None:
            raise DataNotFoundError(message="folder_not_found")
        if not parent["action"]["can_create_subfolder"]:
            raise DataValidationError(message="folder_action_not_permitted")

        depth = self.relative_depth(parent["folder"])
        if depth is None:
            raise DataValidationError(message="invalid_folder_scope")
        limit = await self.folder_depth_limit(ctx.db)
        if depth + 1 > limit:
            raise DataValidationError(message="folder_depth_exceeded")

        await self.call_udin(
            ctx,
            UdinRequest(
                method="POST",
                path=f"/engine/storage/new-folder/{ctx.project_task['project']['uid']}",
                json={"current_path": current_path, "name": name},
                error_message="folder_create_failed",
            ),
        )
        # No file lives here yet, so build_file_tree needs its own row to see this folder.
        ctx.db.add(
            DfEngineUploadFiles(
                name=name,
                type=UploadFileTypes.folder,
                path=f"{current_path}/{name}",
                size=0,
                project_id=ctx.project_task["project"]["id"],
                task_id=ctx.project_task["id"],
                created_by=ctx.user_id,
            )
        )
        await ctx.db.flush()
        return await self.invalidate_and_refresh(ctx)

    async def delete_folder(self, ctx: FileCtx, folder_path: str) -> list[dict[str, Any]]:
        tree = await self.get_tree(ctx)
        folder = self.find_folder(tree, folder_path)
        if folder is None:
            raise DataNotFoundError(message="folder_not_found")
        if not folder["action"]["can_delete"]:
            raise DataValidationError(message="folder_action_not_permitted")
        path = folder["folder"]

        body = await self.call_udin(
            ctx,
            UdinRequest(
                method="DELETE",
                path=f"/engine/storage/delete-folder/{ctx.project_task['project']['uid']}",
                json={"path": path},
                error_message="folder_delete_failed",
            ),
        )
        await self.sync_after(
            "delete-folder",
            ctx.project_task["uid"],
            self.sync_paths(ctx.db, body.get("data") or [], ctx.project_task["id"], ctx.user_id),
        )
        await self.sync_after(
            "delete-folder",
            ctx.project_task["uid"],
            self.delete_folder_rows(ctx.db, path, ctx.project_task["id"], ctx.user_id),
        )
        return await self.invalidate_and_refresh(ctx)

    async def delete_folder_rows(self, db: AsyncSession, path: str, task_id: int, user_id: int) -> None:
        """Delete type=folder rows at/under `path`, now that udin has removed them from disk."""
        rows = await query(
            db=db,
            table=DfEngineUploadFiles,
            filters=(
                DfEngineUploadFiles.task_id == task_id,
                DfEngineUploadFiles.created_by == user_id,
                DfEngineUploadFiles.type == UploadFileTypes.folder,
            ),
        )
        for row in rows:
            if row.path == path or row.path.startswith(f"{path}/"):
                await db.delete(row)
        await db.flush()

    async def delete_files(self, ctx: FileCtx, file_uids: list[UUID]) -> list[dict[str, Any]]:
        tree = await self.get_tree(ctx)
        raw_paths: list[str] = []
        for file_uid in file_uids:
            entry = self.find_file(tree, str(file_uid))
            if entry is None:
                raise DataNotFoundError(message="file_not_found")
            if not entry["action"]["can_delete"]:
                raise DataValidationError(message="file_action_not_permitted")
            raw_paths.append(self.raw_path(entry["path"]))

        await self.call_udin(
            ctx,
            UdinRequest(
                method="DELETE",
                path=f"/engine/storage/delete-files/{ctx.project_task['project']['uid']}",
                json={"sources": raw_paths},
                error_message="files_delete_failed",
            ),
        )
        await self.sync_after(
            "delete-files",
            ctx.project_task["uid"],
            self.delete_paths(ctx.db, raw_paths, ctx.project_task["id"], ctx.user_id),
        )
        return await self.invalidate_and_refresh(ctx)

    async def rename_file(self, ctx: FileCtx, file_uid: UUID, name: str) -> list[dict[str, Any]]:
        tree = await self.get_tree(ctx)
        entry = self.find_file(tree, str(file_uid))
        if entry is None:
            raise DataNotFoundError(message="file_not_found")
        if not entry["action"]["can_rename"]:
            raise DataValidationError(message="file_action_not_permitted")

        body = await self.call_udin(
            ctx,
            UdinRequest(
                method="PATCH",
                path=f"/engine/storage/rename-file/{ctx.project_task['project']['uid']}",
                json={"filepath": self.raw_path(entry["path"]), "name": name},
                error_message="file_rename_failed",
            ),
        )
        await self.sync_after(
            "rename-file",
            ctx.project_task["uid"],
            self.sync_paths(ctx.db, body.get("data") or [], ctx.project_task["id"], ctx.user_id),
        )
        return await self.invalidate_and_refresh(ctx)

    async def rename_folder(self, ctx: FileCtx, folder_path: str, name: str) -> list[dict[str, Any]]:
        tree = await self.get_tree(ctx)
        folder = self.find_folder(tree, folder_path)
        if folder is None:
            raise DataNotFoundError(message="folder_not_found")
        if not folder["action"]["can_rename"]:
            raise DataValidationError(message="folder_action_not_permitted")
        path = folder["folder"]

        body = await self.call_udin(
            ctx,
            UdinRequest(
                method="PATCH",
                path=f"/engine/storage/rename-folder/{ctx.project_task['project']['uid']}",
                json={"path": path, "name": name},
                error_message="folder_rename_failed",
            ),
        )
        new_path = f"{path.rsplit('/', 1)[0]}/{name}"
        await self.sync_after(
            "rename-folder",
            ctx.project_task["uid"],
            self.sync_paths(ctx.db, body.get("data") or [], ctx.project_task["id"], ctx.user_id),
        )
        await self.sync_after(
            "rename-folder",
            ctx.project_task["uid"],
            self.rewrite_folder_prefix(ctx.db, path, new_path, ctx.project_task["id"], ctx.user_id),
        )
        return await self.invalidate_and_refresh(ctx)

    async def move_files(self, ctx: FileCtx, file_uids: list[UUID], destination: str) -> list[dict[str, Any]]:
        tree = await self.get_tree(ctx)
        dest = self.find_folder(tree, destination)
        if dest is None:
            raise DataNotFoundError(message="folder_not_found")
        if not dest["action"]["can_set_as_target_move_file"]:
            raise DataValidationError(message="folder_action_not_permitted")

        raw_paths: list[str] = []
        for file_uid in file_uids:
            entry = self.find_file(tree, str(file_uid))
            if entry is None:
                raise DataNotFoundError(message="file_not_found")
            if not entry["action"]["can_choose_to_move"]:
                raise DataValidationError(message="file_action_not_permitted")
            raw_paths.append(self.raw_path(entry["path"]))

        body = await self.call_udin(
            ctx,
            UdinRequest(
                method="PATCH",
                path=f"/engine/storage/move-files/{ctx.project_task['project']['uid']}",
                json={"sources": raw_paths, "destination": destination},
                error_message="files_move_failed",
            ),
        )
        await self.sync_after(
            "move-files",
            ctx.project_task["uid"],
            self.sync_paths(ctx.db, body.get("data") or [], ctx.project_task["id"], ctx.user_id),
        )
        return await self.invalidate_and_refresh(ctx)

    async def move_folders(self, ctx: FileCtx, folder_paths: list[str], destination: str) -> list[dict[str, Any]]:
        tree = await self.get_tree(ctx)
        dest = self.find_folder(tree, destination)
        if dest is None:
            raise DataNotFoundError(message="folder_not_found")
        if not dest["action"]["can_set_as_target_move_folder"]:
            raise DataValidationError(message="folder_action_not_permitted")

        dest_depth = self.relative_depth(destination)
        if dest_depth is None:
            raise DataValidationError(message="invalid_folder_scope")
        limit = await self.folder_depth_limit(ctx.db)

        sources: list[str] = []
        for folder_path in folder_paths:
            folder = self.find_folder(tree, folder_path)
            if folder is None:
                raise DataNotFoundError(message="folder_not_found")
            if not folder["action"]["can_rename"]:
                raise DataValidationError(message="folder_action_not_permitted")
            if dest_depth + self.subtree_depth(folder) + 1 > limit:
                raise DataValidationError(message="folder_depth_exceeded")
            sources.append(folder["folder"])

        body = await self.call_udin(
            ctx,
            UdinRequest(
                method="PATCH",
                path=f"/engine/storage/move-folders/{ctx.project_task['project']['uid']}",
                json={"sources": sources, "destination": destination},
                error_message="folders_move_failed",
            ),
        )
        await self.sync_after(
            "move-folders",
            ctx.project_task["uid"],
            self.sync_paths(ctx.db, body.get("data") or [], ctx.project_task["id"], ctx.user_id),
        )
        for source in sources:
            new_path = f"{destination}/{source.rsplit('/', 1)[-1]}"
            await self.sync_after(
                "move-folders",
                ctx.project_task["uid"],
                self.rewrite_folder_prefix(ctx.db, source, new_path, ctx.project_task["id"], ctx.user_id),
            )
        return await self.invalidate_and_refresh(ctx)

    async def set_generation_field(self, ctx: FileCtx, result_uids: list[str], mutation: FieldMutation) -> None:
        """Validate + mutate one column on every owned generation result in `result_uids`. Raises a
        single 422 with one error per bad index (`file_uids.{idx}`) rather than an all-or-nothing 404.
        Does not touch the cache or return anything - callers own the refresh, since only they know
        which cached lists their mutation affects."""
        rows = await query(
            db=ctx.db,
            table=DfEngineGenerationResults,
            joins=((DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
            filters=(
                DfEngineGenerationResults.uid.in_(result_uids),  # type: ignore
                DfEngineGenerations.task_id == ctx.project_task["id"],
                DfEngineGenerations.created_by == ctx.user_id,
            ),
        )
        found = {row.uid: row for row in rows}
        errors: dict[str, list[str]] = {}
        for idx, uid in enumerate(result_uids):
            row = found.get(uid)
            if row is None:
                errors[f"file_uids.{idx}"] = ["file_not_found"]
            elif not mutation.is_valid_state(row):
                errors[f"file_uids.{idx}"] = [mutation.invalid_state_message]
        if errors:
            raise DataValidationError(message="file_uids_invalid", error=errors)

        for row in found.values():
            setattr(row, mutation.field, mutation.value)
            ctx.db.add(row)
        await ctx.db.flush()

    async def set_archived_generation(
        self, ctx: FileCtx, result_uids: list[str], is_archieved: bool
    ) -> list[dict[str, Any]]:
        mutation = FieldMutation(
            field="archieved_at",
            value=local_time() if is_archieved else None,
            is_valid_state=(lambda row: row.archieved_at is None and not row.is_main)
            if is_archieved
            else (lambda row: row.archieved_at is not None),
            invalid_state_message="file_already_archived" if is_archieved else "file_not_archived",
        )
        await self.set_generation_field(ctx, result_uids, mutation)
        tree = await self.invalidate_and_refresh(ctx)
        # Re-cache /archieved inline so the next GET is a hit, even though it's not in this response.
        await self.refresh_archived_files(ctx)
        await delete_pattern(ctx.redis, CacheKeys().user_galleries_pattern(ctx.user_id))
        return tree

    async def set_favorited_generation(
        self, ctx: FileCtx, result_uids: list[str], is_favorited: bool
    ) -> list[dict[str, Any]]:
        mutation = FieldMutation(
            field="is_favourite",
            value=is_favorited,
            is_valid_state=(lambda row: not row.is_favourite) if is_favorited else (lambda row: row.is_favourite),
            invalid_state_message="file_already_favourited" if is_favorited else "file_not_favourited",
        )
        await self.set_generation_field(ctx, result_uids, mutation)
        tree = await self.invalidate_and_refresh(ctx)
        # Re-cache /favourited inline so the next GET is a hit.
        await self.refresh_favourited_files(ctx)
        await delete_pattern(ctx.redis, CacheKeys().user_galleries_pattern(ctx.user_id))
        return tree

    async def set_main_generation_result(self, ctx: FileCtx, file_uid: str) -> list[dict[str, Any]]:
        """Flip `is_main` to True on `file_uid`, atomically flipping every other main in its family
        (the root result plus all of its children - not just siblings) to False in the same call -
        never a hard "already main" error, just a silent swap. Re-setting the already-current main
        is a no-op 200."""
        row = await query(
            db=ctx.db,
            table=DfEngineGenerationResults,
            joins=((DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
            filters=(
                DfEngineGenerationResults.uid == file_uid,
                DfEngineGenerations.task_id == ctx.project_task["id"],
                DfEngineGenerations.created_by == ctx.user_id,
            ),
            fetch_one=True,
        )
        if row is None:
            raise DataValidationError(message="file_uid_invalid", error={"file_uid": ["file_not_found"]})

        if not row.is_main:
            current_mains = await query(
                db=ctx.db,
                table=DfEngineGenerationResults,
                filters=(
                    or_(
                        DfEngineGenerationResults.id == row.parent_id,
                        DfEngineGenerationResults.parent_id == row.parent_id,
                        DfEngineGenerationResults.parent_id == row.id,
                    ),
                    DfEngineGenerationResults.is_main.is_(True),  # type: ignore
                    DfEngineGenerationResults.id != row.id,
                ),
            )
            for current_main in current_mains:
                current_main.is_main = False
                ctx.db.add(current_main)
            row.is_main = True
            ctx.db.add(row)
            await ctx.db.flush()

        await delete_pattern(ctx.redis, CacheKeys().references_picker_pattern(ctx.user_id))
        await delete_pattern(ctx.redis, CacheKeys().user_galleries_pattern(ctx.user_id))
        return await self.invalidate_and_refresh(ctx)

    def raw_path(self, url: str) -> str:
        """Reverse `format_udin_url`: strip the udin base URL and percent-decode back to the raw storage path."""
        prefix = f"{UDIN_BASE_URL}/"
        return unquote(url[len(prefix) :] if url.startswith(prefix) else url)

    def find_folder(self, tree: list[dict[str, Any]], folder_path: str) -> dict[str, Any] | None:
        """Locate a folder node anywhere in the tree by its exact `folder` path."""
        for node in tree:
            if node["folder"] == folder_path:
                return node
            found = self.find_folder(node["childs"], folder_path)
            if found is not None:
                return found
        return None

    def find_file(self, tree: list[dict[str, Any]], file_uid: str) -> dict[str, Any] | None:
        """Locate a file entry anywhere in the tree by its `uid`."""
        for node in tree:
            found = next((f for f in node["files"] if f["uid"] == file_uid), None)
            if found is not None:
                return found
            found = self.find_file(node["childs"], file_uid)
            if found is not None:
                return found
        return None

    def file_entry(self, file: dict[str, Any], user_id: int) -> dict[str, Any]:
        """Build one file's response entry (used both nested inside `build_file_tree` and
        flat by `build_flat_file_list`). `actionable` mirrors whether the file sits at/under
        one of the four upload/generated type roots - equivalent to checking its parent
        folder's scope, but derived straight from the path so it needs no tree context.

        Archive/favourite are independent locks - a result can be both at once. Only
        `can_choose_to_move` still keys off `is_archived` (archived generated files are frozen
        in place)."""
        actionable = self.type_root_of(file["path"]) is not None
        is_owner = file["created_by"] == user_id
        is_generated = "/generated" in file["path"]
        is_archived = file.get("archieved_at") is not None
        is_favourite = bool(file.get("is_favourite"))
        is_main = bool(file.get("is_main", True))
        file_type = "video" if "/videos/" in file["path"] else "image"
        can_act = actionable and is_owner and is_generated
        generation = file.get("generation") or {}
        return {
            "uid": file["uid"],
            "name": file["path"].rsplit("/", 1)[-1],
            "type": file_type,
            "path": format_udin_url(file["path"]),
            "size": format_size(file["size"]),
            "md5": file.get("md5"),
            "creator": format_user_employees(file.get("created_by_user")),
            "updater": format_user_employees(file.get("updated_by_user")),
            "is_main": is_main,
            "source": "generated" if is_generated else "upload",
            "kind": generation.get("kind"),
            "model": generation.get("model"),
            "prompt": generation.get("prompt"),
            "cost": format_idr(generation.get("cost"), USD_TO_IDR_RATE),
            "action": {
                "can_fetch_detail": True,
                "can_rename": actionable and is_owner,
                "can_delete": actionable and is_owner and not is_generated,
                "can_choose_to_move": actionable and is_owner and not (is_generated and is_archived),
                "can_archieve": can_act and not is_archived and not is_main,
                "can_unarchieve": can_act and is_archived,
                "can_favorited": can_act and not is_favourite,
                "can_unfavorited": can_act and is_favourite,
                "can_set_main": can_act and bool(file.get("parent_id")) and not is_main,
            },
        }

    def build_flat_file_list(self, files: list[dict[str, Any]], user_id: int) -> list[dict[str, Any]]:
        """A one-level list of file entries — no folder nesting. Used for the
        archived/favourited views, which are always generation results only."""
        return [self.file_entry(file, user_id) for file in files]

    def build_file_tree(self, files: list[dict[str, Any]], user_id: int) -> list[dict[str, Any]]:
        """Nest uploaded and generated files into one folder tree, mirroring udin's
        `upload/<type>` and `generated/<type>` layouts.

        A file action requires the file's own `created_by` to match `user_id`.
        A folder action requires *every* file nested under it to belong to
        `user_id` — renaming/deleting a folder cascades to everything inside it.
        """
        if not files:
            return []

        segments = ("upload", "generated")
        base_path = self.base_of(files[0]["path"])
        type_roots = {f"{base_path}/{segment}/{kind}" for segment in segments for kind in ("images", "videos")}

        def folder_scope(path: str) -> tuple[bool, bool]:
            if path in type_roots:
                return True, False
            return False, any(path.startswith(f"{root}/") for root in type_roots)

        tree: list[dict[str, Any]] = []
        folder_owners: dict[str, set[int]] = {}
        root_ids = {f["id"] for f in files if "parent_id" in f and f.get("parent_id") is None}
        families: dict[int, list[dict[str, Any]]] = {}  # root id -> its members (root + children), 1 level deep

        for file in files:
            is_folder_row = file.get("type") == UploadFileTypes.folder
            parts = file["path"].strip("/").split("/")
            folders = parts if is_folder_row else parts[:-1]

            current_level = tree
            built_path = ""
            last_node: dict[str, Any] | None = None
            visited: list[dict[str, Any]] = []

            for folder in folders:
                built_path = f"{built_path}/{folder}" if built_path else folder
                node: dict[str, Any] | None = next((n for n in current_level if n["folder"] == built_path), None)
                if node is None:
                    is_root, is_inside = folder_scope(built_path)
                    actionable = is_root or is_inside
                    node = {
                        "folder": built_path,
                        "type": "folder",
                        "action": {
                            "can_fetch_detail": True,
                            "can_rename": is_inside,
                            "can_create_subfolder": actionable,
                            "can_delete": is_inside,
                            "can_set_as_target_move_file": actionable,
                            "can_set_as_target_move_folder": actionable,
                        },
                        "files": [],
                        "childs": [],
                    }
                    current_level.append(node)
                visited.append(node)
                last_node = node
                current_level = node["childs"]

            assert last_node is not None
            if not is_folder_row:
                entry = self.file_entry(file, user_id)
                parent_id = file.get("parent_id")
                family_id = None
                if "parent_id" in file:
                    # Family = a root result plus its direct children, capped at 1 level: a child
                    # whose parent_id doesn't match a known root (a "grandchild") gets no family.
                    family_id = file["id"] if parent_id is None else (parent_id if parent_id in root_ids else None)
                if family_id is not None:
                    families.setdefault(family_id, []).append(
                        {"entry": entry, "is_main": bool(file.get("is_main")), "fallback": last_node["files"]}
                    )
                else:
                    last_node["files"].append(entry)

            for node in visited:
                folder_owners.setdefault(node["folder"], set()).add(file["created_by"])

        for members in families.values():
            # Whichever member currently holds is_main is shown at the top; the rest become its
            # "variants" - so promoting a child (set-main) moves it into the root's old slot.
            main = next((m for m in members if m["is_main"]), members[0])
            main["entry"]["variants"] = [m["entry"] for m in members if m is not main]
            main["fallback"].append(main["entry"])

        def apply_folder_ownership(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                all_owned = folder_owners.get(node["folder"]) == {user_id}
                node["action"] = {
                    key: (value if key == "can_fetch_detail" else value and all_owned)
                    for key, value in node["action"].items()
                }
                apply_folder_ownership(node["childs"])

        apply_folder_ownership(tree)
        return tree
