from sqlalchemy.exc import IntegrityError
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
    NAME_MAX,
    DeleteFilesPayload,
    FolderPayload,
    MoveFilesPayload,
    MoveFoldersPayload,
    RenameFilePayload,
    SetArchivedPayload,
    SetFavoritedPayload,
)
from sqlalchemy import or_, update
from sqlalchemy.orm import load_only
from schemas.response import Response
from services.api_caller import APICaller
from services.redis import CacheKeys, delete_pattern, invalidate_project_files
from services.mysql import query
from services.mysql.model import (
    DfEngineGenerationFavourites,
    DfEngineGenerationResults,
    DfEngineGenerations,
    DfEngineGenerationUploads,
    DfEngineUploadFiles,
)
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_generations import GenerationStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.tasks.udin_uploader import udin_uploader
from error import AuthorizationError, DataNotFoundError, DataValidationError
from services.dto.asynced.employees import get_employee, assigned_to_task
from services.files import (
    apply_folder_changes,
    invalidate_generation_lists,
    task_scope,
    build_file_tree_refactored,
    resolve_project_scope,
    format_file_tree_refactored,
    call_udin_folder,
    ensure_task_assigned,
    find_folder,
    delete_upload_files_under,
    folder_scope,
    get_folder_depth_limit,
    has_override,
    resolve_files,
    project_root_path,
)
from services.dto.asynced.projects import get_project, get_project_task
from services.dto.asynced.files import (
    get_user_uploaded_file,
    get_user_uploaded_files,
    get_user_uploaded_files_refactored,
)
from services.dto.format_response import FileAction, TreeFile
from services.dto.asynced.generation_files import (
    get_archieved_files,
    get_failed_upload_generations,
    get_favourited_files,
    get_generation_files,
    get_generation_main_variants,
    get_generation_main_file_detail,
    get_generation_main_refactored,
)
from utils import local_time
from utils.formatter import format_datetime, format_size
from services.search.dispatch import dispatch_search_sync
from services.dto.asynced.generation_files import overlay_favourites
from services.search.query import search_project_files

cache_key = CacheKeys()
UPLOAD_TIMEOUT = Timeout(connect=10, read=600, write=120, pool=10)


class FilesController(CoreDependencies):
    @controller.get(
        "/files/failed-uploads/{project_uid}",
        summary="Get generations that need a manual re-upload.",
        description="Shows generated images, edited images and videos of a project whose upload to Udin failed after every automatic retry. Only your own generations are listed, unless you have an override role. Optionally narrow by task or song (`task_uid`), or search by prompt, model name, song or task name.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_to_fetch_failed_upload_generations(
        self,
        project_uid: UUID = Path(..., description="Project UID."),
        task_uid: Optional[UUID] = Query(None, description="Project task UID or project song UID."),
        search: Optional[str] = Query(None, description="Match prompt, model name, song or task name."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        can_override = has_override(self.user["roles"])
        try:
            project = await get_project(ctx, project_uid=project_uid)
            task_id = None
            song_id = None
            if task_uid:
                project_task = await get_project_task(ctx, task_uid)
                if project_task["project_id"] != project["id"]:
                    raise DataNotFoundError(message="project_task_not_found")
                task_id = project_task["id"] if project_task["is_song"] is False else None
                song_id = project_task["id"] if project_task["is_song"] is True else None

            response.data = await get_failed_upload_generations(
                ctx,
                user_id,
                can_override,
                project_id=project["id"],
                task_id=task_id,
                song_id=song_id,
                search=search,
            )
            logging.info(
                f"[get-failed-uploads] user={user_id} project_uid={project_uid} task_uid={task_uid} "
                f"fetched {len(response.data)} generations"
            )
        except BaseError as e:
            logging.warning(
                f"[get-failed-uploads] user={user_id} project_uid={project_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(
                f"[get-failed-uploads] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.patch(
        "/files/failed-uploads/{generation_uid}",
        summary="Re-upload a failed generation to Udin.",
        description="Queues a manual re-upload to Udin for a generation whose automatic retries are exhausted. Only the creator or a user with an override role can do this. The upload runs in the background.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_to_reupload_failed_generation(
        self, generation_uid: UUID = Path(..., description="Generation UID (`generation_uid` from the list).")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        can_override = has_override(self.user["roles"])
        lock = None
        try:
            row = await query(
                self.db,
                DfEngineGenerations,
                columns=(DfEngineGenerations, DfEngineGenerationUploads.upload_status),
                joins=((DfEngineGenerationUploads, DfEngineGenerationUploads.generation_id == DfEngineGenerations.id),),
                filters=(DfEngineGenerations.uid == str(generation_uid),),  # type: ignore
                fetch_one=True,
            )
            if not row:
                raise DataNotFoundError(
                    message="generation_not_found", error={"generation_uid": ["generation_not_found"]}
                )
            generation, upload_status = row
            if generation.created_by != user_id and not can_override:
                raise AuthorizationError(
                    message="reupload_not_creator", error={"generation_uid": ["reupload_not_creator"]}
                )
            if upload_status != UploadStatuses.failed:
                raise DataValidationError(
                    message="reupload_not_permitted", error={"generation_uid": ["reupload_not_permitted"]}
                )

            key = cache_key.generation_reupload_lock(generation.id)
            if not await self.redis.set(key, user_id, nx=True, ex=400):  # ttl > the uploader's 360s time limit
                raise BaseError(
                    status_code=status.HTTP_409_CONFLICT,
                    message="reupload_in_progress",
                    error={"generation_uid": ["reupload_in_progress"]},
                )
            lock = key

            async def refresh_caches() -> None:
                await delete_pattern(
                    self.redis, cache_key.generation_files_main_list_pattern(generation.task_id or generation.song_id)
                )
                await invalidate_generation_lists(ctx, {user_id, generation.created_by})
                await invalidate_project_files(self.redis, cache_key, generation.project_id)

            # galleries list processing/success only: show it as in-flight until the worker finishes
            generation.status = GenerationStatuses.processing
            self.db.add(generation)
            await self.db.commit()
            await refresh_caches()
            try:
                udin_uploader.delay(generation.id, generation.created_by)  # type: ignore
            except Exception:
                generation.status = GenerationStatuses.failed
                self.db.add(generation)
                await self.db.commit()
                await refresh_caches()
                raise

            items = await get_failed_upload_generations(ctx, user_id, True, generation_uid=str(generation_uid))
            response.data = items[0] if items else None
            response.message = resolve_message("reupload_queued", current_lang.get())
            logging.info(f"[reupload-failed-generation] user={user_id} generation_uid={generation_uid} queued")
        except BaseError as e:
            logging.warning(
                f"[reupload-failed-generation] user={user_id} generation_uid={generation_uid} "
                f"rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            if lock:
                await self.redis.delete(lock)
            logging.error(
                f"[reupload-failed-generation] user={user_id} generation_uid={generation_uid} failed\n"
                f"{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.get(
        "/files/archieves",
        summary="Get archived files.",
        description="Shows every generated file you've archived. Optionally narrow by project, task or song id.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_to_fetch_archived_files(
        self,
        project_id: Optional[int] = Query(None, description="Only archived files of this project."),
        task_id: Optional[int] = Query(None, description="Only archived files of this project task."),
        song_id: Optional[int] = Query(None, description="Only archived files of this song."),
        search: Optional[str] = Query(
            None, description="Match file name, file path, project name or project task name."
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            archieved_files = await get_archieved_files(ctx, user_id, project_id, task_id, song_id, search)
            logging.info(
                f"[get-archived-files] user={user_id} project_id={project_id} task_id={task_id} "
                f"song_id={song_id} search={search} fetched {len(archieved_files)} archived files"
            )
            response.data = archieved_files
        except Exception:
            logging.error(f"[get-archived-files] user={user_id} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/favorites",
        summary="Get favorited files.",
        description="Shows every generated file you've marked as a favorite. Optionally narrow by project, task or song id.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_to_fetch_favourited_files(
        self,
        project_id: Optional[int] = Query(None, description="Only favorites of this project."),
        task_id: Optional[int] = Query(None, description="Only favorites of this project task."),
        song_id: Optional[int] = Query(None, description="Only favorites of this song."),
        search: Optional[str] = Query(
            None, description="Match file name, file path, project name or project task name."
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            favourited_files = await get_favourited_files(ctx, user_id, project_id, task_id, song_id, search)
            logging.info(
                f"[get-favourited-files] user={user_id} project_id={project_id} task_id={task_id} "
                f"song_id={song_id} search={search} fetched {len(favourited_files)} favourited files"
            )
            response.data = favourited_files
        except Exception:
            logging.error(f"[get-favourited-files] user={user_id} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.post(
        "/files/archieve/{file_uid}",
        summary="Set archieve file.",
        description="Hides a generated file from the main view, or brings it back. Only the creator can do this.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_file_uid_to_set_archieve_file(
        self, schema: SetArchivedPayload, file_uid: UUID = Path(..., description="Generated file UID.")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        try:
            row = await query(
                self.db,
                DfEngineGenerationResults,
                filters=(DfEngineGenerationResults.uid == str(file_uid),),  # type: ignore
                fetch_one=True,
            )
            if not row:
                logging.warning(f"[set-archive-file] user={user_id} file_uid={file_uid} not found")
                raise DataNotFoundError(message="file_not_found", error={"file_uid": ["file_not_found"]})
            if row.created_by != user_id:  # creator only, override roles included
                logging.warning(f"[set-archive-file] user={user_id} file_uid={file_uid} not the creator")
                raise AuthorizationError(
                    message="file_archive_not_creator", error={"file_uid": ["file_archive_not_creator"]}
                )
            if (row.archieved_at is not None) == schema.is_archieved:  # already in the requested state
                raise DataNotFoundError(message="file_not_found", error={"file_uid": ["file_not_found"]})
            if schema.is_archieved and row.is_main:  # a main version can never be archived
                raise DataValidationError(
                    message="file_archive_not_permitted", error={"file_uid": ["file_archive_not_permitted"]}
                )

            row.archieved_at = local_time() if schema.is_archieved else None
            row.updated_by = user_id
            self.db.add(row)
            await self.db.flush()

            group = row.parent_id or row.id
            family = await query(
                self.db,
                DfEngineGenerationResults,
                options=(load_only(DfEngineGenerationResults.uid),),
                filters=(
                    or_(
                        DfEngineGenerationResults.id == group,  # type: ignore
                        DfEngineGenerationResults.parent_id == group,  # type: ignore
                    ),
                ),
            )
            for member in family:
                await self.redis.delete(cache_key.generation_files_main_detail(member.uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variant_detail(member.uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variants_detail(member.uid))  # type: ignore
            generation = await query(
                self.db,
                DfEngineGenerations,
                options=(
                    load_only(DfEngineGenerations.task_id, DfEngineGenerations.song_id, DfEngineGenerations.project_id),
                ),
                filters=(DfEngineGenerations.id == row.generation_id,),  # type: ignore
                fetch_one=True,
            )
            await delete_pattern(
                self.redis, cache_key.generation_files_main_list_pattern(generation.task_id or generation.song_id)
            )
            await invalidate_project_files(self.redis, cache_key, generation.project_id)
            for pattern in cache_key.generation_files_user_lists_patterns(user_id):
                await delete_pattern(self.redis, pattern)
            logging.info(f"[set-archive-file] user={user_id} file_uid={file_uid} is_archieved={schema.is_archieved}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[set-archive-file] user={user_id} file_uid={file_uid} failed\n{traceback.format_exc()}")
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

    @controller.post(
        "/files/favorite/{file_uid}",
        summary="Set favourite file.",
        description="Marks a generated file as your favorite, or removes it from your favorites. Anyone can favorite any generated file; favorites are per user.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_file_uid_to_set_favorite_file(
        self, schema: SetFavoritedPayload, file_uid: UUID = Path(..., description="Generated file UID.")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        try:
            result = await query(
                self.db,
                DfEngineGenerationResults,
                options=(load_only(DfEngineGenerationResults.id),),
                filters=(DfEngineGenerationResults.uid == str(file_uid),),  # type: ignore
                fetch_one=True,
            )
            if not result:
                logging.warning(f"[set-favourite-file] user={user_id} file_uid={file_uid} not found")
                raise DataNotFoundError(message="file_not_found", error={"file_uid": ["file_not_found"]})

            favourite = await query(
                self.db,
                DfEngineGenerationFavourites,
                filters=(
                    DfEngineGenerationFavourites.user_id == user_id,  # type: ignore
                    DfEngineGenerationFavourites.result_id == result.id,  # type: ignore
                ),
                fetch_one=True,
            )
            if schema.is_favorited:
                if favourite:
                    raise DataValidationError(
                        message="file_already_favourited", error={"file_uid": ["file_already_favourited"]}
                    )
                self.db.add(DfEngineGenerationFavourites(user_id=user_id, result_id=result.id))
            else:
                if not favourite:
                    raise DataValidationError(
                        message="file_not_favourited", error={"file_uid": ["file_not_favourited"]}
                    )
                await self.db.delete(favourite)
            await self.db.flush()

            # only this viewer's favourite state changed: their own lists are the only stale cache
            for pattern in cache_key.generation_files_user_lists_patterns(user_id):
                await delete_pattern(self.redis, pattern)
            await delete_pattern(self.redis, cache_key.generation_files_references_picker_pattern(user_id))
            logging.info(f"[set-favourite-file] user={user_id} file_uid={file_uid} is_favorited={schema.is_favorited}")
        except BaseError:
            raise
        except Exception:
            logging.error(f"[set-favourite-file] user={user_id} file_uid={file_uid} failed\n{traceback.format_exc()}")
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
                options=(
                    load_only(
                        DfEngineGenerations.task_id,
                        DfEngineGenerations.song_id,
                        DfEngineGenerations.created_by,
                        DfEngineGenerations.project_id,
                    ),
                ),
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
            await delete_pattern(
                self.redis, cache_key.generation_files_main_list_pattern(generation.task_id or generation.song_id)
            )
            await delete_pattern(self.redis, cache_key.generation_files_references_picker_pattern(user_id))
            await invalidate_generation_lists(ctx, {user_id, generation.created_by})
            await invalidate_project_files(self.redis, cache_key, generation.project_id)
            await dispatch_search_sync(self.db, generations=family_uids)

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
            max_length=1024,
            description="Existing folder to upload into (a path from the file tree). Defaults to the type root: "
            "`upload/images` or `upload/videos`.",
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        can_override = has_override(self.user["roles"])
        try:
            project_task = await get_project_task(ctx, task_uid)

            task_id = project_task["id"] if project_task["is_song"] is False else None
            song_id = project_task["id"] if project_task["is_song"] is True else None
            project_uid = project_task["project"]["uid"]

            if path:
                """
                Perform validation this dir should be exists. If valid then uploaded data will be located in here, otherwise will raised error.
                Error will be 404 due to folder not found or 422 due to system reached limit upload depth.
                Later the ENV will be changed, due to must be synced with udin actual environment.
                """
                path = path.rstrip("/")
                project_dir = f"storage/DF-Engine-DEV/{project_task['project']['name']}_{str(project_uid)[:8]}"
                if not path.startswith(project_dir):
                    raise DataNotFoundError(message="folder_path_not_found", error={"path": ["folder_path_not_found"]})
                if not any(
                    path == f"{project_dir}/upload/{kind}" or path.startswith(f"{project_dir}/upload/{kind}/")
                    for kind in ("images", "videos")
                ):
                    raise DataValidationError(message="invalid_upload_path", error={"path": ["invalid_upload_path"]})

                is_root = path in (f"{project_dir}/upload/images", f"{project_dir}/upload/videos")
                if not is_root:
                    owner = (
                        DfEngineUploadFiles.task_id == task_id  # type: ignore
                        if task_id is not None
                        else DfEngineUploadFiles.song_id == song_id  # type: ignore
                    )
                    # a folder made from the project-level tree has no task/song: it belongs to the whole project
                    project_folder = (
                        (DfEngineUploadFiles.project_id == project_task["project_id"])  # type: ignore
                        & (DfEngineUploadFiles.task_id.is_(None))  # type: ignore
                        & (DfEngineUploadFiles.song_id.is_(None))  # type: ignore
                        & (DfEngineUploadFiles.type == UploadFileTypes.folder)  # type: ignore
                        & (DfEngineUploadFiles.path == path)  # type: ignore
                    )
                    exists = await query(
                        ctx.db,
                        DfEngineUploadFiles,
                        columns=(DfEngineUploadFiles.id,),
                        filters=(
                            or_(
                                project_folder,
                                owner
                                & or_(
                                    (DfEngineUploadFiles.type == UploadFileTypes.folder)  # type: ignore
                                    & (DfEngineUploadFiles.path == path),  # type: ignore
                                    DfEngineUploadFiles.path.startswith(path + "/", autoescape=True),  # type: ignore
                                ),
                            ),
                        ),
                        fetch_one=True,
                    )
                    if exists is None:
                        raise DataNotFoundError(message="folder_not_found", error={"path": ["folder_not_found"]})

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
                        params={"project_name": project_task["project"]["name"], **({"path": path} if path else {})},
                        content=request.stream(),
                    )
            except TimeoutException:
                logging.error(f"[upload-files] user={user_id} task_uid={task_uid} udin timed out")
                raise BaseError(status_code=status.HTTP_504_GATEWAY_TIMEOUT, message="upload_timeout")

            try:
                body: dict[str, Any] = upstream.json() if upstream.content else {}
            except ValueError:  # a success reply that isn't JSON counts as an empty result
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

            uploaded = body.get("data") or []
            rows: list[DfEngineUploadFiles] = []
            for item in uploaded:
                rows.append(
                    DfEngineUploadFiles(
                        name=item["name"],
                        type=UploadFileTypes.video if "/videos/" in item["path"] else UploadFileTypes.image,
                        path=item["path"],
                        md5=item.get("md5"),
                        size=item["size"],
                        project_id=project_task["project_id"],
                        task_id=task_id,
                        song_id=song_id,
                        created_by=user_id,
                    )
                )
            self.db.add_all(rows)

            try:
                await self.db.flush()
            except IntegrityError:  # task/song deleted by the owning service after it was resolved
                raise DataNotFoundError(message="project_task_not_found")
            await delete_pattern(
                self.redis,
                cache_key.user_files_pattern(task_id=task_id, song_id=song_id),
            )
            await delete_pattern(self.redis, cache_key.generation_files_references_picker_pattern(user_id))
            await invalidate_project_files(self.redis, cache_key, project_task["project_id"])
            await dispatch_search_sync(self.db, uploads=[row.uid for row in rows])

            logging.info(
                f"[upload-files] user={user_id} task_uid={task_uid} saved={len(uploaded)} rows, cache invalidated"
            )

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
        "/files/{project_uid}",
        summary="Get file trees.",
        description="Retrieve the file tree of a project, including its folders, uploaded files and generated files. Set `my_task` to true to return only the files that belong to the current user.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_get_user_files(
        self,
        project_uid: UUID = Path(..., description="Project UID."),
        search: Optional[str] = Query(None, description="Search by filepath or filename."),
        task_uid: Optional[UUID] = Query(None, description="Project task UID or project song UID."),
        my_task: bool = False,
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        can_override = has_override(self.user["roles"])
        try:
            project = await get_project(ctx, project_uid=project_uid)

            if search:
                uploaded, generated = await search_project_files(
                    str(project_uid), search, ("image", "image_edit", "video", "folder"), user_id, can_override, my_task
                )
                if not uploaded and not generated:
                    response.data = None
                else:
                    await overlay_favourites(ctx, generated, user_id)
                    response.data = format_file_tree_refactored(
                        uploaded,
                        generated,
                        await get_folder_depth_limit(ctx),
                        project_root_path(project),
                        flash_files=True,
                    )
            else:
                response.data = await build_file_tree_refactored(
                    ctx, project["id"], user_id, task_uid, my_task=my_task, can_override=can_override
                )
        except BaseError as e:
            logging.warning(
                f"[get-files] user={user_id} project_uid={project_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[get-files] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/files/{project_uid}/folders",
        summary="Get folder details.",
        description="Retrieve a single folder from the file tree of a project, matched by `path`. Returns 404 if the folder does not exist.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_task_uid_to_get_user_folder_details(
        self,
        project_uid: UUID = Path(..., description="Project UID."),
        path: str = Query(
            ...,
            min_length=1,
            max_length=1024,
            description="Full folder path, matching a `path` value from the file tree (e.g. storage/DF-Engine/<name>/upload/images).",
        ),
        task_uid: Optional[UUID] = Query(None, description="Project task UID or project song UID."),
        my_task: bool = Query(
            False, description="If true, only include uploaded files that belong to the current user."
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        can_override = has_override(self.user["roles"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project = await get_project(ctx, project_uid=project_uid)
            file_tree = await build_file_tree_refactored(
                ctx, project["id"], user_id, task_uid, my_task=my_task, can_override=can_override
            )
            folder_details = find_folder(file_tree, path.strip("/"))
            if not folder_details:
                logging.warning(
                    f"[get-folder] user={user_id} project_uid={project_uid} path={path!r} my_task={my_task} not found root={file_tree.get('path')}"
                )
                raise DataNotFoundError(message="folder_not_found")
            logging.info(
                f"[get-folder] user={user_id} project_uid={project_uid} path={path!r} my_task={my_task} "
                f"files={len(folder_details.get('files') or [])} children={len(folder_details.get('children') or [])}"
            )
            response.data = folder_details

        except BaseError as e:
            logging.warning(
                f"[get-folder] user={user_id} project_uid={project_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[get-folder] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}")
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
        "/files/{project_uid}/folders",
        summary="Create folder.",
        description="Create a new folder under `path` (a folder from the file tree) in the file tree of a project. Returns the refreshed file tree.",
        status_code=status.HTTP_201_CREATED,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_project_uid_to_create_a_folder(
        self,
        schema: FolderPayload,
        project_uid: UUID = Path(..., description="Project UID."),
        task_uid: Optional[UUID] = Query(None, description="Project task UID or project song UID (optional scope)."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project, project_task = await resolve_project_scope(ctx, project_uid, task_uid)

            # await ensure_task_assigned(ctx, project_task, user_id)

            parent = find_folder(
                await build_file_tree_refactored(
                    ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
                ),
                schema.path,
            )
            if not parent:
                raise DataNotFoundError(message="folder_not_found", error={"path": ["folder_not_found"]})
            if not parent["action"]["can_create_subfolder"]:
                key = "folder_depth_exceeded" if len(folder_scope(schema.path)) == 2 else "invalid_folder_scope"
                logging.warning(
                    f"[create-folder] user={user_id} project_uid={project_uid} path={schema.path!r} refused "
                    f"{key} depth_limit={await get_folder_depth_limit(ctx)}"
                )
                raise DataValidationError(message=key, error={"path": [key]})

            created = await call_udin_folder(
                "POST",
                "new-folder",
                project["uid"],
                project["name"],
                user_id,
                {"current_path": schema.path, "name": schema.name},
                "folder_create_failed",
                "create-folder",
            )
            is_song = project_task["is_song"]
            self.db.add(
                DfEngineUploadFiles(
                    name=created["path"].rsplit("/", 1)[-1],  # Udin's answer is the source of truth
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

            response.data = await build_file_tree_refactored(
                ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
            )
            response.message = resolve_message("folder_created", current_lang.get())
            logging.info(f"[create-folder] user={user_id} project_uid={project_uid} created={created['path']!r}")
        except BaseError as e:
            logging.warning(
                f"[create-folder] user={user_id} project_uid={project_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[create-folder] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{project_uid}/folders",
        summary="Update folder.",
        description="Rename the folder at `path` to `name`. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_project_uid_to_update_a_folder(
        self,
        schema: FolderPayload,
        project_uid: UUID = Path(..., description="Project UID."),
        task_uid: Optional[UUID] = Query(None, description="Project task UID or project song UID (optional scope)."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project, project_task = await resolve_project_scope(ctx, project_uid, task_uid)

            # await ensure_task_assigned(ctx, project_task, user_id)

            folder = find_folder(
                await build_file_tree_refactored(
                    ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
                ),
                schema.path,
            )
            if not folder:
                raise DataNotFoundError(message="folder_not_found", error={"path": ["folder_not_found"]})
            if not folder["action"]["can_rename"]:
                raise DataValidationError(
                    message="folder_rename_not_permitted", error={"path": ["folder_rename_not_permitted"]}
                )

            if schema.name == folder["name"]:  # nothing to rename
                response.data = await build_file_tree_refactored(
                    ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
                )
                response.message = resolve_message("folder_renamed", current_lang.get())
                return response

            pairs = await call_udin_folder(
                "PATCH",
                "rename-folder",
                project["uid"],
                project["name"],
                user_id,
                {"path": schema.path, "name": schema.name},
                "folder_rename_failed",
                "rename-folder",
            )
            new_path = f"{schema.path.rpartition('/')[0]}/{schema.name}"
            await apply_folder_changes(ctx, project_task, user_id, pairs=pairs or [], moves=[(schema.path, new_path)])

            response.data = await build_file_tree_refactored(
                ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
            )
            response.message = resolve_message("folder_renamed", current_lang.get())
            logging.info(
                f"[rename-folder] user={user_id} project_uid={project_uid} {schema.path!r} -> {new_path!r} files={len(pairs or [])}"
            )
        except BaseError as e:
            logging.warning(
                f"[rename-folder] user={user_id} project_uid={project_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[rename-folder] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.delete(
        "/files/{project_uid}/folders",
        summary="Delete folder.",
        description="Delete the folder at `path`. In an upload folder, its files (at any depth) are permanently deleted with it; in a generated folder they are moved up into the parent folder, never deleted. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_project_uid_to_delete_a_folder(
        self,
        project_uid: UUID = Path(..., description="Project UID."),
        task_uid: Optional[UUID] = Query(None, description="Project task UID or project song UID (optional scope)."),
        path: str = Query(
            ...,
            min_length=1,
            max_length=1024,
            description="Full folder path, matching a `path` value from the file tree (e.g. storage/DF-Engine/<name>/upload/images/drafts).",
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        path = path.strip("/")
        try:
            project, project_task = await resolve_project_scope(ctx, project_uid, task_uid)

            # await ensure_task_assigned(ctx, project_task, user_id)

            folder = find_folder(
                await build_file_tree_refactored(
                    ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
                ),
                path,
            )
            if not folder:
                raise DataNotFoundError(message="folder_not_found")
            if not folder["action"]["can_delete"]:
                raise DataValidationError(
                    message="folder_delete_not_permitted", error={"path": ["folder_delete_not_permitted"]}
                )

            deleted_upload_uids: list[str] = []
            if folder_scope(path)[:1] == ("upload",):
                deleted_upload_uids = await delete_upload_files_under(
                    ctx, project["uid"], project["name"], user_id, path
                )

            pairs = await call_udin_folder(
                "DELETE",
                "delete-folder",
                project["uid"],
                project["name"],
                user_id,
                {"path": path},
                "folder_delete_failed",
                "delete-folder",
            )
            await apply_folder_changes(ctx, project_task, user_id, pairs=pairs or [], deleted=[path])
            await dispatch_search_sync(self.db, deleted_uploads=deleted_upload_uids)

            response.data = await build_file_tree_refactored(
                ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
            )
            response.message = resolve_message("folder_deleted", current_lang.get())
            logging.info(
                f"[delete-folder] user={user_id} project_uid={project_uid} path={path!r} promoted={len(pairs or [])}"
            )
        except BaseError as e:
            logging.warning(
                f"[delete-folder] user={user_id} project_uid={project_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[delete-folder] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{project_uid}/folders/move",
        summary="Move folders.",
        description="Move one or more folders into `destination`. Uploaded folders can only go under upload and generated folders under generated, and the type (images or videos) must match. Returns the refreshed file tree.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_project_uid_to_move_folders(
        self,
        schema: MoveFoldersPayload,
        project_uid: UUID = Path(..., description="Project UID."),
        task_uid: Optional[UUID] = Query(None, description="Project task UID or project song UID (optional scope)."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project, project_task = await resolve_project_scope(ctx, project_uid, task_uid)

            # await ensure_task_assigned(ctx, project_task, user_id)

            tree = await build_file_tree_refactored(
                ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
            )
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
                logging.warning(f"[move-folders] user={user_id} project_uid={project_uid} invalid={errors}")
                raise DataValidationError(message=next(iter(errors.values()))[0], error=errors)

            sources = [
                source
                for source in schema.folder_paths
                if not any(source.startswith(other + "/") for other in schema.folder_paths)
            ]
            pairs = await call_udin_folder(
                "PATCH",
                "move-folders",
                project["uid"],
                project["name"],
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

            response.data = await build_file_tree_refactored(
                ctx, project["id"], user_id, task_uid, can_override=has_override(self.user["roles"])
            )
            response.message = resolve_message("folders_moved", current_lang.get())
            logging.info(
                f"[move-folders] user={user_id} project_uid={project_uid} moved={len(sources)} "
                f"destination={schema.destination!r} files={len(pairs or [])}"
            )
        except BaseError as e:
            logging.warning(
                f"[move-folders] user={user_id} project_uid={project_uid} rejected ({e.status_code}): {e.message}"
            )
            raise
        except Exception:
            logging.error(f"[move-folders] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{source}/{file_uid}",
        summary="Rename file.",
        description="Rename a generated or uploaded file. A typed media extension is ignored: the file's real extension is always kept. Letters, numbers, spaces and _ - . # ( ) @ & only; leading/trailing dots are removed. Only the creator or a user with an override role can do this. Returns the refreshed file tree.",
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
            # Udin keeps only `Path(name).stem` + the real extension, so always send the stored one last
            new_name = schema.name + PurePosixPath(rows[0].path).suffix
            if len(new_name) > NAME_MAX:
                raise DataValidationError(message="file_name_too_long", error={"name": ["file_name_too_long"]})
            if new_name == PurePosixPath(rows[0].path).name:  # nothing to rename
                response.data = await build_file_tree_refactored(
                    ctx, project_task["project_id"], user_id, can_override=has_override(self.user["roles"])
                )
                response.message = resolve_message("file_renamed", current_lang.get())
                return response
            pairs = await call_udin_folder(
                "PATCH",
                "rename-file",
                project["uid"],
                project["name"],
                user_id,
                {"filepath": rows[0].path, "name": new_name},
                "file_rename_failed",
                "rename-file",
            )
            await apply_folder_changes(ctx, project_task, user_id, pairs=pairs or [])

            response.data = await build_file_tree_refactored(
                ctx, project_task["project_id"], user_id, can_override=has_override(self.user["roles"])
            )
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

            tree = await build_file_tree_refactored(
                ctx, project_task["project_id"], user_id, can_override=has_override(self.user["roles"])
            )
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
                project["name"],
                user_id,
                {"sources": [row.path for row in rows], "destination": schema.destination},
                "files_move_failed",
                "move-files",
            )
            await apply_folder_changes(ctx, project_task, user_id, pairs=pairs or [])

            response.data = await build_file_tree_refactored(
                ctx, project_task["project_id"], user_id, can_override=has_override(self.user["roles"])
            )
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
                project["name"],
                user_id,
                {"sources": [row.path for row in rows]},
                "files_delete_failed",
                "delete-files",
            )
            for row in rows:
                await ctx.redis.delete(cache_key.user_file_detail(row.uid))  # type: ignore
                await self.db.delete(row)
            await apply_folder_changes(ctx, project_task, user_id)
            await invalidate_project_files(self.redis, cache_key, project_task["project_id"])
            await dispatch_search_sync(
                self.db, deleted_uploads=[row.uid for row in rows if row.type != UploadFileTypes.folder]
            )

            response.data = await build_file_tree_refactored(
                ctx, project_task["project_id"], user_id, can_override=has_override(self.user["roles"])
            )
            response.message = resolve_message("files_deleted", current_lang.get())
            logging.info(f"[delete-files] user={user_id} deleted={len(rows)}")
        except BaseError as e:
            logging.warning(f"[delete-files] user={user_id} rejected ({e.status_code}): {e.message}")
            raise
        except Exception:
            logging.error(f"[delete-files] user={user_id} failed\n{traceback.format_exc()}")
            raise ServiceError()
        return response
