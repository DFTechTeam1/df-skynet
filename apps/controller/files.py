import mimetypes
from contextlib import AsyncExitStack
from pathlib import PurePosixPath
import traceback
from typing import Any, AsyncIterator, Optional, Literal
from urllib.parse import quote
from uuid import UUID
from fastapi import Path, Request, status, Query
from httpx import Timeout, TimeoutException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from error import BaseError, ServiceError
from services.dto import ConnectionContext
from log import logging
from middlewares.lang import current_lang, resolve_message
from schemas.payload.files import (
    DeleteFilesPayload,
    FolderPayload,
    MoveFilesPayload,
    MoveFoldersPayload,
    RenameFilePayload,
    SetArchivedPayload,
    SetFavoritedPayload,
)
from sqlalchemy import or_, update
from schemas.response import Response
from services.api_caller import APICaller
from services.redis import CacheKeys, delete_pattern, get_json, set_json
from services.mysql import query
from services.mysql.model import DfEngineGenerationResults, DfEngineGenerations, DfEngineUploadFiles
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from error import DataNotFoundError, DataValidationError
from services.files import (
    apply_folder_changes,
    invalidate_generation_lists,
    task_scope,
    build_file_tree,
    call_udin_folder,
    ensure_task_assigned,
    find_folder,
    delete_upload_files_under,
    folder_scope,
    get_folder_depth_limit,
    has_override,
    resolve_files,
)
from services.dto.asynced.projects import get_project, get_project_task
from services.dto.asynced.files import get_user_uploaded_file
from services.dto.format_response import FileAction, TreeFile
from services.dto.asynced.generation_files import (
    get_archieved_files,
    get_favourited_files,
    get_generation_files,
    get_generation_main_variants,
    get_generation_main_file_detail,
)
from utils import local_time
from utils.formatter import format_datetime

cache_key = CacheKeys()
UPLOAD_TIMEOUT = Timeout(connect=10, read=600, write=120, pool=10)


class FilesController(CoreDependencies):
    @controller.get(
        "/files/{task_uid}/archieved",
        summary="View archived files.",
        description="Shows files that have been archived.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_fetch_archived_files(
        self, task_uid: UUID = Path(..., description="Task UID (project task or song).")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_task = await get_project_task(ctx, task_uid)
            logging.info(
                f"[get-archived-files] user={user_id} task_uid={task_uid} resolved project_id={project_task['project_id']}"
            )

            task_id, song_id = task_scope(project_task)
            archieved_files = await get_archieved_files(
                ctx, task_id, song_id, user_id, has_override(self.user["roles"])
            )
            logging.info(
                f"[get-archived-files] user={user_id} task_uid={task_uid} fetched {len(archieved_files)} archived files"
            )

            response.data = archieved_files
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-archived-files] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/favourited",
        summary="Get favorited files.",
        description="Shows files you've marked as favorites.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_fetch_favourited_files(
        self,
        task_uid: UUID = Path(..., description="Task UID (project task or song)."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_task = await get_project_task(ctx, task_uid)
            logging.info(
                f"[get-favourited-files] user={user_id} task_uid={task_uid} resolved project_id={project_task['project_id']}"
            )

            task_id, song_id = task_scope(project_task)
            favourited_files = await get_favourited_files(
                ctx, task_id, song_id, user_id, has_override(self.user["roles"])
            )
            logging.info(
                f"[get-favourited-files] user={user_id} task_uid={task_uid} fetched {len(favourited_files)} favourited files"
            )

            response.data = favourited_files
        except BaseError:
            raise
        except Exception:
            logging.error(f"[get-favourited-files] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/archieve",
        summary="Set archieve files.",
        description="Hides the selected files from the main view, or brings them back.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_set_archieve_files(
        self, schema: SetArchivedPayload, task_uid: UUID = Path(..., description="Task UID (project task or song).")
    ) -> Response:
        response = Response()
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        user_id = int(self.user["user_id"])
        can_override = has_override(self.user["roles"])
        scope_user = None if can_override else user_id  # override roles may archive anyone's file in the project

        try:
            project_task = await get_project_task(ctx, task_uid)
            logging.info(
                f"[set-archive-files] user={user_id} task_uid={task_uid} resolved project_id={project_task['project_id']}"
            )

            task_id, song_id = task_scope(project_task)
            requested_file_uids = [str(uid) for uid in schema.file_uids]
            archieved_files = []
            archivable_files = []

            if schema.is_archieved is True:
                generation_files = await get_generation_files(ctx, scope_user, task_id, song_id)
                archivable_files = [record for record in generation_files if record["archieved_at"] is None]
                validated_file_uids = {record["file_uid"] for record in archivable_files}
                logging.info(
                    f"[set-archive-files] user={user_id} task_uid={task_uid} loaded {len(archivable_files)} archivable files"
                )
            else:
                archieved_files = [
                    record
                    for record in await get_generation_files(ctx, scope_user, task_id, song_id)
                    if record["archieved_at"] is not None
                ]
                validated_file_uids = {record["file_uid"] for record in archieved_files}
                logging.info(
                    f"[set-archive-files] user={user_id} task_uid={task_uid} loaded {len(archieved_files)} archived files"
                )

            errors = {
                f"file_uids.{idx}": ["file_not_found"]
                for idx, uid in enumerate(requested_file_uids)
                if uid not in validated_file_uids
            }
            if errors:
                logging.warning(f"[set-archive-files] user={user_id} task_uid={task_uid} invalid file_uids={errors}")
                raise DataNotFoundError(message="file_not_found", error=errors)
            if schema.is_archieved is True:  # a main version can never be archived, whoever asks
                main_uids = {record["file_uid"] for record in archivable_files if record.get("is_main")}
                errors = {
                    f"file_uids.{idx}": ["file_archive_not_permitted"]
                    for idx, uid in enumerate(requested_file_uids)
                    if uid in main_uids
                }
                if errors:
                    logging.warning(f"[set-archive-files] user={user_id} task_uid={task_uid} main files={errors}")
                    raise DataValidationError(message="file_archive_not_permitted", error=errors)

            archived_at = local_time()
            rows = await query(
                self.db,
                DfEngineGenerationResults,
                filters=(
                    DfEngineGenerationResults.uid.in_(requested_file_uids),  # type: ignore
                    DfEngineGenerationResults.is_main.is_(False),  # type: ignore
                ),
            )
            previous_updaters = {row.updated_by for row in rows}
            for row in rows:
                row.archieved_at = archived_at if schema.is_archieved else None
                row.updated_by = user_id
                self.db.add(row)
            await self.db.flush()
            # the main file's cached detail embeds its non-archived variants: drop the whole family's detail caches
            groups = {row.parent_id or row.id for row in rows}
            family = await query(
                self.db,
                DfEngineGenerationResults,
                filters=(
                    or_(
                        DfEngineGenerationResults.id.in_(groups),  # type: ignore
                        DfEngineGenerationResults.parent_id.in_(groups),  # type: ignore
                    ),
                ),
            )
            for member in family:
                await self.redis.delete(cache_key.generation_files_main_detail(member.uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variant_detail(member.uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variants_detail(member.uid))  # type: ignore
            logging.info(
                f"[set-archive-files] user={user_id} task_uid={task_uid} "
                f"updated {len(rows)} rows file_uids={requested_file_uids} is_archieved={schema.is_archieved}"
            )

            value = archived_at if schema.is_archieved else None
            user_generation_files_key = cache_key.generation_files_result_list(user_id, task_id, song_id)
            cached_generation_files = None if can_override else await get_json(self.redis, user_generation_files_key)
            if cached_generation_files is not None:
                for record in cached_generation_files:
                    if record["file_uid"] not in requested_file_uids:
                        continue
                    record["archieved_at"] = format_datetime(value)
                    record["flag_archieved_at"] = value.isoformat() if value else None
                    record["action"]["can_archieve"] = value is None
                    record["action"]["can_unarchieve"] = value is not None
                await set_json(self.redis, user_generation_files_key, cached_generation_files)
                logging.info(
                    f"[set-archive-files] user={user_id} task_uid={task_uid} cache patched key={user_generation_files_key} file_uids={requested_file_uids}"
                )
            else:
                logging.info(
                    f"[set-archive-files] user={user_id} task_uid={task_uid} cache miss key={user_generation_files_key}, skipped patch"
                )

            archived_generations_key = cache_key.generation_files_archived_list(user_id, task_id, song_id)
            if schema.is_archieved is False:
                archieved_files = [
                    record for record in archieved_files if record["file_uid"] not in requested_file_uids
                ]
            else:
                newly_archived = [
                    {
                        **record,
                        "archieved_at": format_datetime(archived_at),
                        "flag_archieved_at": archived_at.isoformat(),
                        "action": {**record["action"], "can_archieve": False, "can_unarchieve": True},
                    }
                    for record in archivable_files
                    if record["file_uid"] in requested_file_uids
                ]
                archieved_files = sorted(
                    list(
                        {
                            r["file_uid"]: r
                            for r in await get_archieved_files(ctx, task_id, song_id, user_id) + newly_archived
                        }.values()
                    ),
                    key=lambda record: record["flag_archieved_at"],
                    reverse=True,
                )

            if can_override:
                # cached lists are per viewer and the response mixes owners: clear them instead of patching
                await invalidate_generation_lists(ctx, {user_id, *(row.created_by for row in rows), *previous_updaters})
                archieved_files = await get_archieved_files(ctx, task_id, song_id, user_id, True)
            else:
                await set_json(self.redis, archived_generations_key, archieved_files)
            logging.info(
                f"[set-archive-files] user={user_id} task_uid={task_uid} cache updated key={archived_generations_key} count={len(archieved_files)}"
            )

            response.data = archieved_files
        except BaseError:
            raise
        except Exception:
            logging.error(f"[set-archive-files] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/download/{file_uid}",
        summary="Download a file.",
        description=(
            "Downloads a file to your device. Use `source=generated` (default) for a generated image, "
            "edited image or video, or `source=upload` for a file uploaded to a project. "
            "Any signed-in user can download any file."
        ),
        tags=["Files"],
    )
    async def files_with_file_uid_to_download_generated_file(
        self,
        file_uid: UUID = Path(..., description="File UID."),
        source: Literal["upload", "generated"] = Query("generated", description="Where `file_uid` comes from."),
    ) -> StreamingResponse:
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        user_id = int(self.user["user_id"])
        try:
            if source == "upload":
                record = await get_user_uploaded_file(ctx, file_uid)
            else:
                record = (await get_generation_files(ctx, file_uids=[str(file_uid)]))[0]  # not owner-scoped
            content_type = mimetypes.guess_type(record["name"])[0] or "application/octet-stream"
            source_url = record["url"] if source == "upload" else record["path"]
            stack = AsyncExitStack()
            try:
                caller = await stack.enter_async_context(APICaller(headers={"X-API-Key": UDIN_API_KEY}))
                upstream = await stack.enter_async_context(caller.stream("GET", source_url))
                upstream.raise_for_status()
            except BaseException:
                await stack.aclose()
                raise

            async def body() -> AsyncIterator[bytes]:
                try:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                finally:
                    await stack.aclose()

            logging.info(f"[download-file] user={user_id} file_uid={file_uid} streaming name={record['name']}")
            return StreamingResponse(
                body(),
                media_type=content_type,
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(record['name'])}"},
                background=BackgroundTask(stack.aclose),
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[download-file] user={user_id} file_uid={file_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()

    @controller.patch(
        "/files/{task_uid}/favorite",
        summary="Set favourite files.",
        description="Marks the selected files as favorites, or removes them from favorites. Users with an override role can do this on anyone's file in the project.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_set_favorite_file(
        self, schema: SetFavoritedPayload, task_uid: UUID = Path(..., description="Task UID (project task or song).")
    ) -> Response:
        response = Response()
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        user_id = int(self.user["user_id"])
        can_override = has_override(self.user["roles"])
        scope_user = None if can_override else user_id  # override roles may favourite anyone's file in the project
        try:
            project_task = await get_project_task(ctx, task_uid)
            logging.info(
                f"[set-favourite-files] user={user_id} task_uid={task_uid} resolved project_id={project_task['project_id']}"
            )

            task_id, song_id = task_scope(project_task)
            requested_file_uids = [str(uid) for uid in schema.file_uids]
            favourited_files = []
            favouritable_files = []

            if schema.is_favorited is True:
                generation_files = await get_generation_files(ctx, scope_user, task_id, song_id)
                favouritable_files = [record for record in generation_files if record["favourited_at"] is None]
                validated_file_uids = {record["file_uid"] for record in favouritable_files}
                logging.info(
                    f"[set-favourite-files] user={user_id} task_uid={task_uid} loaded {len(favouritable_files)} favouritable files"
                )
            else:
                favourited_files = await get_favourited_files(ctx, task_id, song_id, user_id)
                if can_override:
                    favourited_files = [
                        record
                        for record in await get_generation_files(ctx, None, task_id, song_id)
                        if record["favourited_at"] is not None
                    ]
                validated_file_uids = {record["file_uid"] for record in favourited_files}
                logging.info(
                    f"[set-favourite-files] user={user_id} task_uid={task_uid} loaded {len(favourited_files)} favourited files"
                )

            errors = {
                f"file_uids.{idx}": ["file_not_found"]
                for idx, uid in enumerate(requested_file_uids)
                if uid not in validated_file_uids
            }
            if errors:
                logging.warning(f"[set-favourite-files] user={user_id} task_uid={task_uid} invalid file_uids={errors}")
                raise DataNotFoundError(message="file_not_found", error=errors)

            favourited_at = local_time()
            rows = await query(
                self.db,
                DfEngineGenerationResults,
                filters=(DfEngineGenerationResults.uid.in_(requested_file_uids),),  # type: ignore
            )
            previous_updaters = {row.updated_by for row in rows}
            for row in rows:
                row.favourited_at = favourited_at if schema.is_favorited else None
                row.updated_by = user_id
                self.db.add(row)
            await self.db.flush()

            groups = {row.parent_id or row.id for row in rows}
            family = await query(
                self.db,
                DfEngineGenerationResults,
                filters=(
                    or_(
                        DfEngineGenerationResults.id.in_(groups),  # type: ignore
                        DfEngineGenerationResults.parent_id.in_(groups),  # type: ignore
                    ),
                ),
            )
            for member in family:
                await self.redis.delete(cache_key.generation_files_main_detail(member.uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variant_detail(member.uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variants_detail(member.uid))  # type: ignore
            generation_ids = {member.generation_id for member in family if member.generation_id}
            affected_tasks = {project_task["id"]}
            if generation_ids:
                generations = await query(
                    self.db,
                    DfEngineGenerations,
                    filters=(DfEngineGenerations.id.in_(generation_ids),),  # type: ignore
                )
                affected_tasks |= {g.task_id for g in generations if g.task_id}
            for affected in affected_tasks:
                await delete_pattern(self.redis, cache_key.generation_files_main_list_pattern(affected))
            logging.info(
                f"[set-favourite-files] user={user_id} task_uid={task_uid} "
                f"updated {len(rows)} rows file_uids={requested_file_uids} is_favorited={schema.is_favorited}"
            )

            value = favourited_at if schema.is_favorited else None
            user_generation_files_key = cache_key.generation_files_result_list(user_id, task_id, song_id)
            cached_generation_files = None if can_override else await get_json(self.redis, user_generation_files_key)
            if cached_generation_files is not None:
                for record in cached_generation_files:
                    if record["file_uid"] not in requested_file_uids:
                        continue
                    record["favourited_at"] = format_datetime(value)
                    record["flag_favourited_at"] = value.isoformat() if value else None
                    record["action"]["can_favorited"] = value is None
                    record["action"]["can_unfavorited"] = value is not None
                await set_json(self.redis, user_generation_files_key, cached_generation_files)
                logging.info(
                    f"[set-favourite-files] user={user_id} task_uid={task_uid} cache patched key={user_generation_files_key} file_uids={requested_file_uids}"
                )
            else:
                logging.info(
                    f"[set-favourite-files] user={user_id} task_uid={task_uid} cache miss key={user_generation_files_key}, skipped patch"
                )

            favourited_generations_key = cache_key.generation_files_favourited_list(user_id, task_id, song_id)
            if schema.is_favorited is False:
                favourited_files = [
                    record for record in favourited_files if record["file_uid"] not in requested_file_uids
                ]
            else:
                newly_favourited = [
                    {
                        **record,
                        "favourited_at": format_datetime(favourited_at),
                        "flag_favourited_at": favourited_at.isoformat(),
                        "action": {**record["action"], "can_favorited": False, "can_unfavorited": True},
                    }
                    for record in favouritable_files
                    if record["file_uid"] in requested_file_uids
                ]
                favourited_files = sorted(
                    list(
                        {
                            r["file_uid"]: r
                            for r in await get_favourited_files(ctx, task_id, song_id, user_id) + newly_favourited
                        }.values()
                    ),
                    key=lambda record: record["flag_favourited_at"],
                    reverse=True,
                )

            if can_override:
                await invalidate_generation_lists(ctx, {user_id, *(row.created_by for row in rows), *previous_updaters})
                favourited_files = await get_favourited_files(ctx, task_id, song_id, user_id, True)
            else:
                await set_json(self.redis, favourited_generations_key, favourited_files)
            logging.info(
                f"[set-favourite-files] user={user_id} task_uid={task_uid} cache updated key={favourited_generations_key} count={len(favourited_files)}"
            )

            response.data = favourited_files
        except BaseError:
            raise
        except Exception:
            logging.error(f"[set-favourite-files] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/set-main/{file_uid}",
        summary="Set generated file as the main version.",
        description="Makes this file the featured version among its related versions. Only the creator or a user with an override role can do this.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_file_uid_to_set_main_generation_file(
        self,
        file_uid: UUID = Path(..., description="Generation result UID to set as main."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            can_override = has_override(self.user["roles"])
            generation_variants = await get_generation_main_variants(ctx, file_uid, user_id)
            target = next((gen for gen in generation_variants if gen["file_uid"] == str(file_uid)), None)
            is_owner = bool(target and target["creator"] and target["creator"]["user_id"] == user_id)
            if target is None or target["is_main"] or not (is_owner or can_override):
                raise DataValidationError(message="file_uid_invalid", error={"file_uid": ["file_not_found"]})

            family_uids = [str(gen["file_uid"]) for gen in generation_variants]
            generation = await query(
                self.db,
                DfEngineGenerations,
                joins=((DfEngineGenerationResults, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
                filters=(DfEngineGenerationResults.uid == str(file_uid),),
                fetch_one=True,
            )
            await self.db.execute(
                update(DfEngineGenerationResults)
                .where(DfEngineGenerationResults.uid.in_(family_uids))  # type: ignore
                .values(is_main=DfEngineGenerationResults.uid == str(file_uid), updated_by=user_id)
            )
            await self.db.flush()

            for uid in family_uids:
                await self.redis.delete(cache_key.generation_files_main_detail(uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variant_detail(uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variants_detail(uid))  # type: ignore
            await delete_pattern(self.redis, cache_key.generation_files_main_list_pattern(generation.task_id))
            await delete_pattern(self.redis, cache_key.generation_files_references_picker_pattern(user_id))
            await invalidate_generation_lists(ctx, {user_id, generation.created_by})

            response.data = await get_generation_main_file_detail(ctx, file_uid, user_id, can_override)
            response.message = resolve_message("main_generation_set", current_lang.get())
            logging.info(
                f"[set-main-generation] user={user_id} file_uid={file_uid} task_id={generation.task_id} "
                f"project_id={generation.project_id} demoted={len(family_uids) - 1}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[set-main-generation] user={user_id} file_uid={file_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.post(
        "/files/{task_uid}/uploads",
        summary="Upload to Udin.",
        description="Upload your photos or videos to a task or song. Photos can be JPG, JPEG or PNG, and videos can be MP4.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_upload_files(
        self,
        request: Request,
        task_uid: UUID = Path(..., description="Task UID (project task or song)."),
        path: Optional[str] = Query(
            None,
            description="Existing folder to upload into (a path from the file tree). Defaults to the type root: "
            "`upload/images` or `upload/videos`.",
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_task = await get_project_task(ctx, task_uid)
            project_uid = project_task["project"]["uid"]
            is_song = project_task["is_song"]
            if path and not find_folder(
                await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"]), path
            ):
                raise DataNotFoundError(message="folder_not_found", error={"path": ["folder_not_found"]})
            logging.info(
                f"[upload-files] user={user_id} task_uid={task_uid} start is_song={is_song} "
                f"project_id={project_task['project_id']}"
            )

            try:
                async with APICaller(
                    base_url=UDIN_BASE_URL,
                    headers={
                        "X-API-Key": UDIN_API_KEY,
                        "Content-Type": request.headers.get("content-type", ""),
                        **(
                            {"Content-Length": request.headers["content-length"]}
                            if "content-length" in request.headers
                            else {}
                        ),
                    },
                    timeout=UPLOAD_TIMEOUT,  # type: ignore
                ) as caller:
                    upstream = await caller.udin(
                        "POST",
                        f"/engine/storage/upload-files/{project_uid}",
                        user_id=user_id,
                        params={"path": path} if path else None,
                        content=request.stream(),
                    )
            except TimeoutException:
                logging.error(f"[upload-files] user={user_id} task_uid={task_uid} udin timed out")
                raise BaseError(status_code=status.HTTP_504_GATEWAY_TIMEOUT, message="upload_timeout")

            logging.info(
                f"[upload-files] user={user_id} task_uid={task_uid} udin replied status={upstream.status_code}"
            )
            try:
                body: dict[str, Any] = upstream.json() if upstream.content else {}
            except ValueError:
                body = {}

            if upstream.is_error:
                logging.warning(
                    f"[upload-files] user={user_id} task_uid={task_uid} udin rejected "
                    f"status={upstream.status_code} error={body.get('error')}"
                )
                raise BaseError(
                    status_code=upstream.status_code,
                    message="upload_failed",
                    error=body.get("error"),
                )

            uploaded: list[dict[str, Any]] = body.get("data") or []
            for item in uploaded:
                self.db.add(
                    DfEngineUploadFiles(
                        name=item["name"],
                        type=UploadFileTypes.video if "/videos/" in item["path"] else UploadFileTypes.image,
                        path=item["path"],
                        md5=item.get("md5"),
                        size=item["size"],
                        project_id=project_task["project_id"],
                        task_id=None if is_song else project_task["id"],
                        song_id=project_task["id"] if is_song else None,
                        created_by=user_id,
                    )
                )
            await self.db.flush()
            await delete_pattern(
                self.redis,
                cache_key.user_files_pattern(
                    task_id=None if is_song else project_task["id"],
                    song_id=project_task["id"] if is_song else None,
                ),
            )
            await delete_pattern(self.redis, cache_key.generation_files_references_picker_pattern(user_id))
            logging.info(
                f"[upload-files] user={user_id} task_uid={task_uid} saved={len(uploaded)} rows, cache invalidated"
            )

            response.data = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            response.message = "Files successfully uploaded."
            logging.info(f"[upload-files] user={user_id} task_uid={task_uid} done uploaded={len(uploaded)}")
        except BaseError as e:
            logging.warning(
                f"[upload-files] user={user_id} task_uid={task_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[upload-files] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}",
        summary="Get file trees.",
        description="Retrieve the file tree of a task or song, including its folders and uploaded files. Set `my_task` to true to return only the files that belong to the current user.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_get_user_files(
        self,
        task_uid: UUID = Path(..., description="Task UID (project task or song)."),
        my_task: bool = False,
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_task = await get_project_task(ctx, task_uid)
            response.data = await build_file_tree(ctx, project_task, user_id, my_task, self.user["roles"])
            logging.info(
                f"[get-files] user={user_id} task_uid={task_uid} my_task={my_task} root={response.data.get('path')}"
            )
        except BaseError as e:
            logging.warning(f"[get-files] user={user_id} task_uid={task_uid} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[get-files] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{task_uid}/folders",
        summary="Get folder details.",
        description="Retrieve a single folder from the file tree of a task or song, matched by `path`. Returns 404 if the folder does not exist.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_get_user_folder_details(
        self,
        task_uid: UUID = Path(..., description="Task UID (project task or song)."),
        path: str = Query(
            ...,
            description="Full folder path, matching a `path` value from the file tree (e.g. storage/DF-Engine/<name>/upload/images).",
        ),
        my_task: bool = Query(
            False, description="If true, only include uploaded files that belong to the current user."
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_task = await get_project_task(ctx, task_uid)
            file_tree = await build_file_tree(ctx, project_task, user_id, my_task, self.user["roles"])
            folder_details = find_folder(file_tree, path.strip("/"))
            if not folder_details:
                logging.warning(
                    f"[get-folder] user={user_id} task_uid={task_uid} path={path!r} my_task={my_task} not found root={file_tree.get('path')}"
                )
                raise DataNotFoundError(message="folder_not_found")
            logging.info(
                f"[get-folder] user={user_id} task_uid={task_uid} path={path!r} my_task={my_task} "
                f"files={len(folder_details.get('files') or [])} children={len(folder_details.get('children') or [])}"
            )
            response.data = folder_details

        except BaseError as e:
            logging.warning(f"[get-folder] user={user_id} task_uid={task_uid} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[get-folder] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/uploaded-files/{file_uid}",
        summary="Get uploaded file details.",
        description="Retrieve a single uploaded file by its UID. Returns 404 if the file does not exist.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_file_uid_to_get_uploaded_file_details(
        self,
        file_uid: UUID = Path(..., description="Uploaded file UID."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            file = await get_user_uploaded_file(ctx, file_uid)
            is_owner = (file.get("creator") or {}).get("user_id") == user_id
            response.data = TreeFile(
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
                action=FileAction.for_upload(is_owner, has_override(self.user["roles"])),
            ).model_dump(mode="json")
            logging.info(f"[get-file] user={user_id} file_uid={file_uid} owner={is_owner}")
        except BaseError as e:
            logging.warning(f"[get-file] user={user_id} file_uid={file_uid} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[get-file] user={user_id} file_uid={file_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.post(
        "/files/{task_uid}/folders",
        summary="Create folder.",
        description="Create a new folder under `path` (a folder from the file tree) in the file tree of a task or song. Only users assigned to the task can do this. Returns the refreshed file tree.",
        status_code=status.HTTP_201_CREATED,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_create_a_folder(
        self, schema: FolderPayload, task_uid: UUID = Path(..., description="Task UID (project task or song).")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_task = await get_project_task(ctx, task_uid)
            # if project_task.get("is_song") and project_task["status"] == SONG_STATUS_COMPLETED:
            #     raise DataValidationError(message="song_task_already_completed")
            # if not project_task.get("is_song") and project_task["status"] != TASK_STATUS_ONPROCESS:
            #     raise DataValidationError(message="project_task_not_onprocess")
            project = await get_project(ctx, project_id=project_task["project_id"])
            # if project['status'] != PROJECT_STATUS_ONGOING:
            #     raise DataValidationError(message="project_not_ongoing")

            # await ensure_task_assigned(ctx, project_task, user_id)

            parent = find_folder(
                await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"]), schema.path
            )
            if not parent:
                raise DataNotFoundError(message="folder_not_found", error={"path": ["folder_not_found"]})
            if not parent["action"]["can_create_subfolder"]:
                key = "folder_depth_exceeded" if len(folder_scope(schema.path)) == 2 else "invalid_folder_scope"
                logging.warning(
                    f"[create-folder] user={user_id} task_uid={task_uid} path={schema.path!r} refused "
                    f"{key} depth_limit={await get_folder_depth_limit(ctx)}"
                )
                raise DataValidationError(message=key, error={"path": [key]})

            created = await call_udin_folder(
                "POST",
                "new-folder",
                project["uid"],
                user_id,
                {"current_path": schema.path, "name": schema.name},
                "folder_create_failed",
                "create-folder",
            )
            is_song = project_task["is_song"]
            self.db.add(
                DfEngineUploadFiles(
                    name=schema.name,
                    type=UploadFileTypes.folder,
                    path=created["path"],
                    size=0,
                    project_id=project_task["project_id"],
                    task_id=None if is_song else project_task["id"],
                    song_id=project_task["id"] if is_song else None,
                    created_by=user_id,
                )
            )
            await apply_folder_changes(ctx, project_task, user_id)

            response.data = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            response.message = resolve_message("folder_created", current_lang.get())
            logging.info(f"[create-folder] user={user_id} task_uid={task_uid} created={created['path']!r}")
        except BaseError as e:
            logging.warning(
                f"[create-folder] user={user_id} task_uid={task_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[create-folder] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/folders",
        summary="Update folder.",
        description="Rename the folder at `path` to `name`. Only users assigned to the task can do this. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_update_a_folder(
        self, schema: FolderPayload, task_uid: UUID = Path(..., description="Task UID (project task or song).")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_task = await get_project_task(ctx, task_uid)
            # if project_task.get("is_song") and project_task["status"] == SONG_STATUS_COMPLETED:
            #     raise DataValidationError(message="song_task_already_completed")
            # if not project_task.get("is_song") and project_task["status"] != TASK_STATUS_ONPROCESS:
            #     raise DataValidationError(message="project_task_not_onprocess")
            project = await get_project(ctx, project_id=project_task["project_id"])
            # if project['status'] != PROJECT_STATUS_ONGOING:
            #     raise DataValidationError(message="project_not_ongoing")

            # await ensure_task_assigned(ctx, project_task, user_id)

            folder = find_folder(
                await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"]), schema.path
            )
            if not folder:
                raise DataNotFoundError(message="folder_not_found", error={"path": ["folder_not_found"]})
            if not folder["action"]["can_rename"]:
                raise DataValidationError(
                    message="folder_rename_not_permitted", error={"path": ["folder_rename_not_permitted"]}
                )

            pairs = await call_udin_folder(
                "PATCH",
                "rename-folder",
                project["uid"],
                user_id,
                {"path": schema.path, "name": schema.name},
                "folder_rename_failed",
                "rename-folder",
            )
            new_path = f"{schema.path.rpartition('/')[0]}/{schema.name}"
            await apply_folder_changes(ctx, project_task, user_id, pairs=pairs or [], moves=[(schema.path, new_path)])

            response.data = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            response.message = resolve_message("folder_renamed", current_lang.get())
            logging.info(
                f"[rename-folder] user={user_id} task_uid={task_uid} {schema.path!r} -> {new_path!r} files={len(pairs or [])}"
            )
        except BaseError as e:
            logging.warning(
                f"[rename-folder] user={user_id} task_uid={task_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[rename-folder] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.delete(
        "/files/{task_uid}/folders",
        summary="Delete folder.",
        description="Delete the folder at `path`. In an upload folder, its files (at any depth) are permanently deleted with it; in a generated folder they are moved up into the parent folder, never deleted. Only users assigned to the task can do this. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_delete_a_folder(
        self,
        task_uid: UUID = Path(..., description="Task UID (project task or song)."),
        path: str = Query(
            ...,
            description="Full folder path, matching a `path` value from the file tree (e.g. storage/DF-Engine/<name>/upload/images/drafts).",
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        path = path.strip("/")
        try:
            project_task = await get_project_task(ctx, task_uid)
            # if project_task.get("is_song") and project_task["status"] == SONG_STATUS_COMPLETED:
            #     raise DataValidationError(message="song_task_already_completed")
            # if not project_task.get("is_song") and project_task["status"] != TASK_STATUS_ONPROCESS:
            #     raise DataValidationError(message="project_task_not_onprocess")
            project = await get_project(ctx, project_id=project_task["project_id"])
            # if project['status'] != PROJECT_STATUS_ONGOING:
            #     raise DataValidationError(message="project_not_ongoing")

            # await ensure_task_assigned(ctx, project_task, user_id)

            folder = find_folder(await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"]), path)
            if not folder:
                raise DataNotFoundError(message="folder_not_found")
            if not folder["action"]["can_delete"]:
                raise DataValidationError(
                    message="folder_delete_not_permitted", error={"path": ["folder_delete_not_permitted"]}
                )

            if folder_scope(path)[:1] == ("upload",):  # uploaded files go with their folder
                await delete_upload_files_under(ctx, project["uid"], user_id, path)

            pairs = await call_udin_folder(
                "DELETE",
                "delete-folder",
                project["uid"],
                user_id,
                {"path": path},
                "folder_delete_failed",
                "delete-folder",
            )
            await apply_folder_changes(ctx, project_task, user_id, pairs=pairs or [], deleted=[path])

            response.data = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            response.message = resolve_message("folder_deleted", current_lang.get())
            logging.info(
                f"[delete-folder] user={user_id} task_uid={task_uid} path={path!r} promoted={len(pairs or [])}"
            )
        except BaseError as e:
            logging.warning(
                f"[delete-folder] user={user_id} task_uid={task_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[delete-folder] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{task_uid}/folders/move",
        summary="Move folders.",
        description="Move one or more folders into `destination`. Uploaded folders can only go under upload and generated folders under generated, and the type (images or videos) must match. Only users assigned to the task can do this. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_move_folders(
        self, schema: MoveFoldersPayload, task_uid: UUID = Path(..., description="Task UID (project task or song).")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_task = await get_project_task(ctx, task_uid)
            # if project_task.get("is_song") and project_task["status"] == SONG_STATUS_COMPLETED:
            #     raise DataValidationError(message="song_task_already_completed")
            # if not project_task.get("is_song") and project_task["status"] != TASK_STATUS_ONPROCESS:
            #     raise DataValidationError(message="project_task_not_onprocess")
            project = await get_project(ctx, project_id=project_task["project_id"])
            # if project['status'] != PROJECT_STATUS_ONGOING:
            #     raise DataValidationError(message="project_not_ongoing")

            # await ensure_task_assigned(ctx, project_task, user_id)

            tree = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            destination = find_folder(tree, schema.destination)
            errors: dict[str, list[str]] = {}
            if not destination:
                errors["destination"] = ["folder_not_found"]
            elif not destination["action"]["can_receive_move"]:
                key = (
                    "folder_depth_exceeded"
                    if len(folder_scope(schema.destination)) == 2
                    else "invalid_folder_move_scope"
                )
                errors["destination"] = [key]

            def height(node: dict[str, Any]) -> int:
                return max((height(child) + 1 for child in node["children"]), default=0)

            depth_limit = await get_folder_depth_limit(ctx)
            for idx, source in enumerate(schema.folder_paths):
                field = f"folder_paths.{idx}"
                folder = find_folder(tree, source)
                if not folder:
                    errors[field] = ["folder_not_found"]
                elif not folder["action"]["can_choose_to_move"]:
                    errors[field] = ["folder_move_not_permitted"]
                elif destination and folder_scope(source) != folder_scope(schema.destination):
                    errors[field] = ["invalid_folder_move_scope"]
                elif schema.destination == source or schema.destination.startswith(source + "/"):
                    errors[field] = ["invalid_folder_move_scope"]
                elif source.rpartition("/")[0] == schema.destination:
                    errors[field] = ["invalid_folder_move_scope"]
                elif destination and (len(schema.destination.split("/")) - 5) + 1 + height(folder) > depth_limit:
                    errors[field] = ["folder_depth_exceeded"]
            if errors:
                logging.warning(f"[move-folders] user={user_id} task_uid={task_uid} invalid={errors}")
                raise DataValidationError(message=next(iter(errors.values()))[0], error=errors)

            # a source nested inside another source travels with it; Udin would fail on the second move
            sources = [
                source
                for source in schema.folder_paths
                if not any(source.startswith(other + "/") for other in schema.folder_paths)
            ]
            pairs = await call_udin_folder(
                "PATCH",
                "move-folders",
                project["uid"],
                user_id,
                {"sources": sources, "destination": schema.destination},
                "folders_move_failed",
                "move-folders",
            )
            await apply_folder_changes(
                ctx,
                project_task,
                user_id,
                pairs=pairs or [],
                moves=[(source, f"{schema.destination}/{source.rsplit('/', 1)[-1]}") for source in sources],
            )

            response.data = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            response.message = resolve_message("folders_moved", current_lang.get())
            logging.info(
                f"[move-folders] user={user_id} task_uid={task_uid} moved={len(sources)} "
                f"destination={schema.destination!r} files={len(pairs or [])}"
            )
        except BaseError as e:
            logging.warning(
                f"[move-folders] user={user_id} task_uid={task_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[move-folders] user={user_id} task_uid={task_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{source}/{file_uid}",
        summary="Rename file.",
        description="Rename a generated or uploaded file (the extension is always kept). Only the creator or a user with an override role can do this. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    # Named to sort after the `files_with_task_uid_*` handlers: routes register alphabetically and this two-segment
    # path would otherwise shadow `PATCH /files/{task_uid}/archieve|favorite|folders`.
    async def files_with_upload_or_generated_source_and_file_uid_to_rename_file(
        self,
        schema: RenameFilePayload,
        source: Literal["generated", "upload"] = Path(..., description="Where the file lives."),
        file_uid: UUID = Path(..., description="File UID."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            rows, project_task = await resolve_files(ctx, source, [file_uid], user_id, self.user["roles"])
            project = await get_project(ctx, project_id=project_task["project_id"])
            pairs = await call_udin_folder(
                "PATCH",
                "rename-file",
                project["uid"],
                user_id,
                # Udin keeps only `Path(name).stem` + the file's extension, so a dot in the user's name would be eaten
                # as an "extension"; append the real one so the name is used literally
                {"filepath": rows[0].path, "name": schema.name + PurePosixPath(rows[0].path).suffix},
                "file_rename_failed",
                "rename-file",
            )
            await apply_folder_changes(ctx, project_task, user_id, pairs=pairs or [])

            response.data = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            response.message = resolve_message("file_renamed", current_lang.get())
            logging.info(f"[rename-file] user={user_id} source={source} file_uid={file_uid} name={schema.name!r}")
        except BaseError as e:
            logging.warning(f"[rename-file] user={user_id} file_uid={file_uid} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[rename-file] user={user_id} file_uid={file_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{source}",
        summary="Move files.",
        description="Move generated or uploaded files into `destination`. Files can only go to a folder of the same storage (upload or generated) and type (images or videos). Only the creator or a user with an override role can do this. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_source_to_move_files(
        self,
        schema: MoveFilesPayload,
        source: Literal["generated", "upload"] = Path(..., description="Where the files live."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            rows, project_task = await resolve_files(ctx, source, schema.file_uids, user_id, self.user["roles"])
            project = await get_project(ctx, project_id=project_task["project_id"])

            tree = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            destination = find_folder(tree, schema.destination)
            errors: dict[str, list[str]] = {}
            if not destination:
                errors["destination"] = ["folder_not_found"]
            elif not destination["action"]["can_receive_move"]:
                key = (
                    "folder_depth_exceeded" if len(folder_scope(schema.destination)) == 2 else "invalid_file_move_scope"
                )
                errors["destination"] = [key]
            for idx, row in enumerate(rows):
                parent = row.path.rpartition("/")[0]
                if source == "generated" and row.archieved_at is not None:
                    errors[f"file_uids.{idx}"] = ["file_move_not_permitted"]
                elif folder_scope(row.path) != folder_scope(schema.destination):
                    errors[f"file_uids.{idx}"] = ["invalid_file_move_scope"]
                elif parent == schema.destination:
                    errors[f"file_uids.{idx}"] = ["file_already_in_folder"]
            if errors:
                logging.warning(f"[move-files] user={user_id} source={source} invalid={errors}")
                raise (
                    DataNotFoundError(message="folder_not_found", error=errors)
                    if "destination" in errors and errors["destination"] == ["folder_not_found"]
                    else DataValidationError(message=next(iter(errors.values()))[0], error=errors)
                )

            pairs = await call_udin_folder(
                "PATCH",
                "move-files",
                project["uid"],
                user_id,
                {"sources": [row.path for row in rows], "destination": schema.destination},
                "files_move_failed",
                "move-files",
            )
            await apply_folder_changes(ctx, project_task, user_id, pairs=pairs or [])

            response.data = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            response.message = resolve_message("files_moved", current_lang.get())
            logging.info(
                f"[move-files] user={user_id} source={source} moved={len(rows)} destination={schema.destination!r}"
            )
        except BaseError as e:
            logging.warning(f"[move-files] user={user_id} source={source} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[move-files] user={user_id} source={source} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.delete(
        "/files/upload",
        summary="Delete uploaded files.",
        description="Permanently delete uploaded files. Generated files cannot be deleted. Only the creator or a user with an override role can do this. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_to_delete_uploaded_files(self, schema: DeleteFilesPayload) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            rows, project_task = await resolve_files(ctx, "upload", schema.file_uids, user_id, self.user["roles"])
            project = await get_project(ctx, project_id=project_task["project_id"])

            await call_udin_folder(
                "DELETE",
                "delete-files",
                project["uid"],
                user_id,
                {"sources": [row.path for row in rows]},
                "files_delete_failed",
                "delete-files",
            )
            for row in rows:
                await ctx.redis.delete(cache_key.user_file_detail(row.uid))  # type: ignore
                await self.db.delete(row)
            await apply_folder_changes(ctx, project_task, user_id)

            response.data = await build_file_tree(ctx, project_task, user_id, roles=self.user["roles"])
            response.message = resolve_message("files_deleted", current_lang.get())
            logging.info(f"[delete-files] user={user_id} deleted={len(rows)}")
        except BaseError as e:
            logging.warning(f"[delete-files] user={user_id} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[delete-files] user={user_id} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response
