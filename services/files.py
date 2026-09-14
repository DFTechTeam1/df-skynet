import time
import traceback
from typing import Any, Coroutine, Optional
from urllib.parse import quote, unquote
from uuid import UUID
from fastapi import status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from error import BaseError, DataNotFoundError, DataValidationError
from log import logging
from services.api_caller import APICaller
from services.mysql import query
from services.mysql.model import DfEngineExternalApiCalls, Users, Employees, ProjectTasks
from services.mysql.model.df_engine_upload_files import DfEngineUploadFiles, UploadFileTypes
from services.mysql.model.df_engine_generations import DfEngineGenerations
from services.mysql.model.df_engine_generation_results import DfEngineGenerationResults
from services.redis import CacheKeys, delete_pattern, get_json, set_json
from utils.serializer import serialize
from utils.formatter import format_user_employees, format_size
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL

# ponytail: static depth cap, overridden later by a per-project/per-task value from the DB.
MAX_FOLDER_DEPTH = 4


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

    async def fetch_file_tree(
        self, db: AsyncSession, project_task: dict[str, Any], user_id: int
    ) -> list[dict[str, Any]]:
        task_files = serialize(
            await query(
                db=db,
                table=DfEngineUploadFiles,
                options=self.creator_updater_loaders(DfEngineUploadFiles),
                filters=(DfEngineUploadFiles.task_id == project_task["id"], DfEngineUploadFiles.created_by == user_id),
            )
        )
        generated_files = serialize(
            await query(
                db=db,
                table=DfEngineGenerationResults,
                joins=((DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
                options=self.creator_updater_loaders(DfEngineGenerationResults),
                filters=(DfEngineGenerations.task_id == project_task["id"], DfEngineGenerations.created_by == user_id),
            )
        )

        return self.build_file_tree(task_files + generated_files, user_id)

    def creator_updater_loaders(self, model: type[Any]) -> tuple[Any, ...]:
        """Eager-load `created_by_user`/`updated_by_user` -> `employees`, for `format_user_employees`."""
        return tuple(
            selectinload(getattr(model, relation))  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname)  # type: ignore
            for relation in ("created_by_user", "updated_by_user")
        )

    def file_url(self, path: str) -> str:
        """Build the udin-streamed URL for a stored path, percent-encoding spaces etc. (keeps `/` unescaped)."""
        return f"{UDIN_BASE_URL}/{quote(path, safe='/')}"

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

    async def get_tree(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int
    ) -> list[dict[str, Any]]:
        """Cache-first file tree fetch, shared by every mutation endpoint before it mutates the tree."""
        cache_key = CacheKeys().user_files(user_id, project_task["id"])
        file_tree = await get_json(redis, cache_key)
        if file_tree is None:
            file_tree = await self.fetch_file_tree(db, project_task, user_id)
            await set_json(redis, cache_key, file_tree)
        return file_tree

    async def invalidate_and_refresh(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int
    ) -> list[dict[str, Any]]:
        """Drop every cached tree/detail key for this task+user, then rebuild and re-cache the tree."""
        await delete_pattern(redis, f"user_files:task={project_task['id']}:user_id={user_id}*")
        file_tree = await self.fetch_file_tree(db, project_task, user_id)
        await set_json(redis, CacheKeys().user_files(user_id, project_task["id"]), file_tree)
        return file_tree

    async def get_folder_detail(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int, folder_path: str
    ) -> dict[str, Any]:
        """Cache-first single-folder lookup, falling back to the full tree on a cache miss."""
        detail_key = CacheKeys().user_folder_detail(user_id, project_task["id"], folder_path)
        folder = await get_json(redis, detail_key)
        if folder is None:
            tree = await self.get_tree(db, redis, project_task, user_id)
            folder = self.find_folder(tree, folder_path)
            if folder is None:
                raise DataNotFoundError(message="folder_not_found")
            await set_json(redis, detail_key, folder)
        return folder

    async def get_file_detail(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int, file_uid: str
    ) -> dict[str, Any]:
        """Cache-first single-file lookup, falling back to the full tree on a cache miss."""
        detail_key = CacheKeys().user_file_detail(user_id, project_task["id"], file_uid)
        file = await get_json(redis, detail_key)
        if file is None:
            tree = await self.get_tree(db, redis, project_task, user_id)
            file = self.find_file(tree, file_uid)
            if file is None:
                raise DataNotFoundError(message="file_not_found")
            await set_json(redis, detail_key, file)
        return file

    async def employee_nickname(self, db: AsyncSession, user_id: int) -> Optional[str]:
        user = await query(
            db=db,
            table=Users,
            options=(selectinload(Users.employees).load_only(Employees.nickname),),  # type: ignore
            filters=(Users.id == user_id,),
            fetch_one=True,
        )
        return user.employees.nickname if user and user.employees else None

    async def call_udin(
        self, db: AsyncSession, user_id: int, method: str, path: str, json: dict[str, Any], message: str
    ) -> dict[str, Any]:
        """Proxy one mutation call to udin, raising `BaseError` with `message` on any non-2xx response.
        Every call (success or failure) is logged to df_engine_external_api_calls as type="udin"."""
        start = time.perf_counter()
        status_code, endpoint, response_headers, body, error_message = None, path, None, {}, None
        try:
            async with APICaller(base_url=UDIN_BASE_URL, headers={"X-API-Key": UDIN_API_KEY}) as caller:
                upstream = await caller.call(method, path, json=json, raise_for_status=False)  # type: ignore
            status_code = upstream.status_code
            endpoint = str(upstream.request.url)
            response_headers = dict(upstream.headers)
            try:
                body: dict[str, Any] = upstream.json() if upstream.content else {}
            except ValueError:
                body = {}
            if status_code >= status.HTTP_400_BAD_REQUEST:
                error_message = message
                # udin often reports the actual reason in "message" rather than a structured "error" - surface it too.
                error = body.get("error") or ({"detail": [body["message"]]} if body.get("message") else None)
                raise BaseError(status_code=status_code, message=message, error=error)
            return body
        finally:
            await self.log_udin_call(
                db, user_id, method, endpoint, json, status_code, response_headers, body, error_message, start
            )

    async def log_udin_call(
        self,
        db: AsyncSession,
        user_id: int,
        method: str,
        endpoint: str,
        request_payload: dict[str, Any] | None,
        status_code: int | None,
        response_headers: dict[str, Any] | None,
        response_body: dict[str, Any] | None,
        error_message: str | None,
        start: float,
    ) -> None:
        try:
            name = await self.employee_nickname(db, user_id)
            db.add(
                DfEngineExternalApiCalls(
                    name=name,
                    type="udin",
                    method=method,
                    endpoint=endpoint,
                    request_payload=request_payload,
                    response_status_code=status_code,
                    response_headers=response_headers,
                    response_body=response_body,
                    error_message=error_message,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )
            )
            await db.flush()
        except Exception:
            logging.error(f"[{endpoint}] failed to write udin call log\n{traceback.format_exc()}")

    async def sync_after(self, endpoint: str, uid: UUID, coro: Coroutine[Any, Any, None]) -> None:
        """Run a post-udin-success DB sync; log and swallow failures since the real mutation already completed."""
        try:
            await coro
        except Exception:
            logging.error(f"[{endpoint}] uid={uid} db-sync failed after udin success\n{traceback.format_exc()}")

    async def create_folder(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int, current_path: str, name: str
    ) -> list[dict[str, Any]]:
        tree = await self.get_tree(db, redis, project_task, user_id)
        parent = self.find_folder(tree, current_path)
        if parent is None:
            raise DataNotFoundError(message="folder_not_found")
        if not parent["actions"]["can_create_subfolder"]:
            raise DataValidationError(message="folder_action_not_permitted")

        type_root = self.type_root_of(parent["folder"])
        if type_root is None:
            raise DataValidationError(message="invalid_folder_scope")
        relative = parent["folder"][len(type_root) :].strip("/")
        depth = 0 if not relative else len(relative.split("/"))
        if depth + 1 > MAX_FOLDER_DEPTH:
            raise DataValidationError(message="folder_depth_exceeded")

        await self.call_udin(
            db,
            user_id,
            "POST",
            f"/engine/storage/new-folder/{project_task['project']['uid']}",
            {"current_path": current_path, "name": name},
            "folder_create_failed",
        )
        # No file lives here yet, so build_file_tree needs its own row to see this folder.
        db.add(
            DfEngineUploadFiles(
                name=name,
                type=UploadFileTypes.folder,
                path=f"{current_path}/{name}",
                size=0,
                project_id=project_task["project"]["id"],
                task_id=project_task["id"],
                created_by=user_id,
            )
        )
        await db.flush()
        return await self.invalidate_and_refresh(db, redis, project_task, user_id)

    async def delete_folder(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int, folder_path: str
    ) -> list[dict[str, Any]]:
        tree = await self.get_tree(db, redis, project_task, user_id)
        folder = self.find_folder(tree, folder_path)
        if folder is None:
            raise DataNotFoundError(message="folder_not_found")
        if not folder["actions"]["can_delete"]:
            raise DataValidationError(message="folder_action_not_permitted")
        path = folder["folder"]

        body = await self.call_udin(
            db,
            user_id,
            "DELETE",
            f"/engine/storage/delete-folder/{project_task['project']['uid']}",
            {"path": path},
            "folder_delete_failed",
        )
        await self.sync_after(
            "delete-folder",
            project_task["uid"],
            self.sync_paths(db, body.get("data") or [], project_task["id"], user_id),
        )
        await self.sync_after(
            "delete-folder",
            project_task["uid"],
            self.delete_folder_rows(db, path, project_task["id"], user_id),
        )
        return await self.invalidate_and_refresh(db, redis, project_task, user_id)

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

    async def delete_files(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int, file_uids: list[UUID]
    ) -> list[dict[str, Any]]:
        tree = await self.get_tree(db, redis, project_task, user_id)
        raw_paths: list[str] = []
        for file_uid in file_uids:
            entry = self.find_file(tree, str(file_uid))
            if entry is None:
                raise DataNotFoundError(message="file_not_found")
            if not entry["actions"]["can_delete"]:
                raise DataValidationError(message="file_action_not_permitted")
            raw_paths.append(self.raw_path(entry["path"]))

        await self.call_udin(
            db,
            user_id,
            "DELETE",
            f"/engine/storage/delete-files/{project_task['project']['uid']}",
            {"sources": raw_paths},
            "files_delete_failed",
        )
        await self.sync_after(
            "delete-files",
            project_task["uid"],
            self.delete_paths(db, raw_paths, project_task["id"], user_id),
        )
        return await self.invalidate_and_refresh(db, redis, project_task, user_id)

    async def rename_file(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int, file_uid: UUID, name: str
    ) -> list[dict[str, Any]]:
        tree = await self.get_tree(db, redis, project_task, user_id)
        entry = self.find_file(tree, str(file_uid))
        if entry is None:
            raise DataNotFoundError(message="file_not_found")
        if not entry["actions"]["can_rename"]:
            raise DataValidationError(message="file_action_not_permitted")

        body = await self.call_udin(
            db,
            user_id,
            "PATCH",
            f"/engine/storage/rename-file/{project_task['project']['uid']}",
            {"filepath": self.raw_path(entry["path"]), "name": name},
            "file_rename_failed",
        )
        await self.sync_after(
            "rename-file",
            project_task["uid"],
            self.sync_paths(db, body.get("data") or [], project_task["id"], user_id),
        )
        return await self.invalidate_and_refresh(db, redis, project_task, user_id)

    async def rename_folder(
        self, db: AsyncSession, redis: Redis, project_task: dict[str, Any], user_id: int, folder_path: str, name: str
    ) -> list[dict[str, Any]]:
        tree = await self.get_tree(db, redis, project_task, user_id)
        folder = self.find_folder(tree, folder_path)
        if folder is None:
            raise DataNotFoundError(message="folder_not_found")
        if not folder["actions"]["can_rename"]:
            raise DataValidationError(message="folder_action_not_permitted")
        path = folder["folder"]

        body = await self.call_udin(
            db,
            user_id,
            "PATCH",
            f"/engine/storage/rename-folder/{project_task['project']['uid']}",
            {"path": path, "name": name},
            "folder_rename_failed",
        )
        new_path = f"{path.rsplit('/', 1)[0]}/{name}"
        await self.sync_after(
            "rename-folder",
            project_task["uid"],
            self.sync_paths(db, body.get("data") or [], project_task["id"], user_id),
        )
        await self.sync_after(
            "rename-folder",
            project_task["uid"],
            self.rewrite_folder_prefix(db, path, new_path, project_task["id"], user_id),
        )
        return await self.invalidate_and_refresh(db, redis, project_task, user_id)

    async def move_files(
        self,
        db: AsyncSession,
        redis: Redis,
        project_task: dict[str, Any],
        user_id: int,
        file_uids: list[UUID],
        destination: str,
    ) -> list[dict[str, Any]]:
        tree = await self.get_tree(db, redis, project_task, user_id)
        dest = self.find_folder(tree, destination)
        if dest is None:
            raise DataNotFoundError(message="folder_not_found")
        if not dest["actions"]["can_set_as_target_move_file"]:
            raise DataValidationError(message="folder_action_not_permitted")

        raw_paths: list[str] = []
        for file_uid in file_uids:
            entry = self.find_file(tree, str(file_uid))
            if entry is None:
                raise DataNotFoundError(message="file_not_found")
            if not entry["actions"]["can_choose_to_move"]:
                raise DataValidationError(message="file_action_not_permitted")
            raw_paths.append(self.raw_path(entry["path"]))

        body = await self.call_udin(
            db,
            user_id,
            "PATCH",
            f"/engine/storage/move-files/{project_task['project']['uid']}",
            {"sources": raw_paths, "destination": destination},
            "files_move_failed",
        )
        await self.sync_after(
            "move-files",
            project_task["uid"],
            self.sync_paths(db, body.get("data") or [], project_task["id"], user_id),
        )
        return await self.invalidate_and_refresh(db, redis, project_task, user_id)

    async def move_folders(
        self,
        db: AsyncSession,
        redis: Redis,
        project_task: dict[str, Any],
        user_id: int,
        folder_paths: list[str],
        destination: str,
    ) -> list[dict[str, Any]]:
        tree = await self.get_tree(db, redis, project_task, user_id)
        dest = self.find_folder(tree, destination)
        if dest is None:
            raise DataNotFoundError(message="folder_not_found")
        if not dest["actions"]["can_set_as_target_move_folder"]:
            raise DataValidationError(message="folder_action_not_permitted")

        sources: list[str] = []
        for folder_path in folder_paths:
            folder = self.find_folder(tree, folder_path)
            if folder is None:
                raise DataNotFoundError(message="folder_not_found")
            if not folder["actions"]["can_rename"]:
                raise DataValidationError(message="folder_action_not_permitted")
            sources.append(folder["folder"])

        body = await self.call_udin(
            db,
            user_id,
            "PATCH",
            f"/engine/storage/move-folders/{project_task['project']['uid']}",
            {"sources": sources, "destination": destination},
            "folders_move_failed",
        )
        await self.sync_after(
            "move-folders",
            project_task["uid"],
            self.sync_paths(db, body.get("data") or [], project_task["id"], user_id),
        )
        for source in sources:
            new_path = f"{destination}/{source.rsplit('/', 1)[-1]}"
            await self.sync_after(
                "move-folders",
                project_task["uid"],
                self.rewrite_folder_prefix(db, source, new_path, project_task["id"], user_id),
            )
        return await self.invalidate_and_refresh(db, redis, project_task, user_id)

    def raw_path(self, url: str) -> str:
        """Reverse `file_url`: strip the udin base URL and percent-decode back to the raw storage path."""
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

        for file in files:
            is_folder_row = file.get("type") == UploadFileTypes.folder
            parts = file["path"].strip("/").split("/")
            folders, filename = (parts, None) if is_folder_row else (parts[:-1], parts[-1])

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
                        "actions": {
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
                _, is_inside = folder_scope(last_node["folder"])
                is_root = last_node["folder"] in type_roots
                actionable = is_root or is_inside
                is_owner = file["created_by"] == user_id
                is_generated = "/generated" in file["path"]
                file_type = "video" if "/videos/" in file["path"] else "image"
                last_node["files"].append(
                    {
                        "uid": file["uid"],
                        "name": filename,
                        "type": file_type,
                        "path": self.file_url(file["path"]),
                        "size": format_size(file["size"]),
                        "md5": file.get("md5"),
                        "creator": format_user_employees(file.get("created_by_user")),
                        "updater": format_user_employees(file.get("updated_by_user")),
                        "actions": {
                            "can_fetch_detail": True,
                            "can_rename": actionable and is_owner,
                            "can_delete": actionable and is_owner and not is_generated,
                            "can_choose_to_move": actionable and is_owner,
                        },
                    }
                )

            for node in visited:
                folder_owners.setdefault(node["folder"], set()).add(file["created_by"])

        def apply_folder_ownership(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                all_owned = folder_owners.get(node["folder"]) == {user_id}
                node["actions"] = {
                    key: (value if key == "can_fetch_detail" else value and all_owned)
                    for key, value in node["actions"].items()
                }
                apply_folder_ownership(node["childs"])

        apply_folder_ownership(tree)
        return tree
