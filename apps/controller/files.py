import mimetypes
import traceback
from typing import AsyncIterator
from urllib.parse import quote
from uuid import UUID
from fastapi import Path, status
from fastapi.responses import StreamingResponse
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from apps.secret import UDIN_API_KEY
from error import BaseError, ServiceError
from services.dto import ConnectionContext
from log import logging
from middlewares.lang import current_lang, resolve_message
from schemas.payload.files import SetArchivedPayload, SetFavoritedPayload
from sqlalchemy import update
from schemas.response import Response
from services.api_caller import APICaller
from services.redis import CacheKeys, delete_pattern, get_json, set_json
from services.mysql import query
from services.mysql.model import DfEngineGenerationResults, DfEngineGenerations
from error import DataNotFoundError, DataValidationError
from services.dto.asynced.projects import get_project
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


class FilesController(CoreDependencies):
    @controller.get(
        "/files/{project_uid}/archieved",
        summary="View archived files.",
        description="Shows files that have been archived.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_uid_to_fetch_archived_files(
        self, project_uid: UUID = Path(..., description="Project UID.")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project = await get_project(ctx, project_uid)
            logging.info(
                f"[get-archived-files] user={user_id} project_uid={project_uid} resolved project_id={project['id']}"
            )

            archieved_files = await get_archieved_files(ctx, project["id"], user_id)
            logging.info(
                f"[get-archived-files] user={user_id} project_uid={project_uid} fetched {len(archieved_files)} archived files"
            )

            response.data = archieved_files
        except BaseError:
            raise
        except Exception:
            logging.error(
                f"[get-archived-files] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.get(
        "/files/{project_uid}/favourited",
        summary="Get favorited files.",
        description="Shows files you've marked as favorites.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_uid_to_fetch_favourited_files(
        self,
        project_uid: UUID = Path(..., description="Project UID."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project = await get_project(ctx, project_uid)
            logging.info(
                f"[get-favourited-files] user={user_id} project_uid={project_uid} resolved project_id={project['id']}"
            )

            favourited_files = await get_favourited_files(ctx, project["id"], user_id)
            logging.info(
                f"[get-favourited-files] user={user_id} project_uid={project_uid} fetched {len(favourited_files)} favourited files"
            )

            response.data = favourited_files
        except BaseError:
            raise
        except Exception:
            logging.error(
                f"[get-favourited-files] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.patch(
        "/files/{project_uid}/archieve",
        summary="Set archieve files.",
        description="Hides the selected files from the main view, or brings them back.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_uid_to_set_archieve_files(
        self, schema: SetArchivedPayload, project_uid: UUID = Path(..., description="Project UID.")
    ) -> Response:
        response = Response()
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        user_id = int(self.user["user_id"])

        try:
            project = await get_project(ctx, project_uid)
            logging.info(
                f"[set-archive-files] user={user_id} project_uid={project_uid} resolved project_id={project['id']}"
            )

            project_id = project["id"]
            requested_file_uids = [str(uid) for uid in schema.file_uids]
            archieved_files = []
            archivable_files = []

            if schema.is_archieved is True:
                generation_files = await get_generation_files(ctx, user_id, project_id=project_id)
                archivable_files = [record for record in generation_files if record["archieved_at"] is None]
                validated_file_uids = {record["file_uid"] for record in archivable_files}
                logging.info(
                    f"[set-archive-files] user={user_id} project_uid={project_uid} loaded {len(archivable_files)} archivable files"
                )
            else:
                archieved_files = await get_generation_files(ctx, user_id, project_id=project_id)
                validated_file_uids = {record["file_uid"] for record in archieved_files}
                logging.info(
                    f"[set-archive-files] user={user_id} project_uid={project_uid} loaded {len(archieved_files)} archived files"
                )

            errors = {
                f"file_uids.{idx}": ["file_not_found"]
                for idx, uid in enumerate(requested_file_uids)
                if uid not in validated_file_uids
            }
            if errors:
                logging.warning(
                    f"[set-archive-files] user={user_id} project_uid={project_uid} invalid file_uids={errors}"
                )
                raise DataNotFoundError(message="file_not_found", error=errors)

            archived_at = local_time()
            rows = await query(
                self.db,
                DfEngineGenerationResults,
                filters=(
                    DfEngineGenerationResults.uid.in_(requested_file_uids),  # type: ignore
                    DfEngineGenerationResults.is_main.is_(False),  # type: ignore
                ),
            )
            for row in rows:
                row.archieved_at = archived_at if schema.is_archieved else None
                self.db.add(row)
            await self.db.flush()
            logging.info(
                f"[set-archive-files] user={user_id} project_uid={project_uid} "
                f"updated {len(rows)} rows file_uids={requested_file_uids} is_archieved={schema.is_archieved}"
            )

            value = archived_at if schema.is_archieved else None
            user_generation_files_key = cache_key.generation_files_result_list(user_id, project_id)
            cached_generation_files = await get_json(self.redis, user_generation_files_key)
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
                    f"[set-archive-files] user={user_id} project_uid={project_uid} cache patched key={user_generation_files_key} file_uids={requested_file_uids}"
                )
            else:
                logging.info(
                    f"[set-archive-files] user={user_id} project_uid={project_uid} cache miss key={user_generation_files_key}, skipped patch"
                )

            archived_generations_key = cache_key.generation_files_archived_list(user_id, project_id)
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
                    newly_archived + await get_archieved_files(ctx, project_id, user_id),
                    key=lambda record: record["flag_archieved_at"],
                    reverse=True,
                )

            await set_json(self.redis, archived_generations_key, archieved_files)
            logging.info(
                f"[set-archive-files] user={user_id} project_uid={project_uid} cache updated key={archived_generations_key} count={len(archieved_files)}"
            )

            response.data = archieved_files
        except BaseError:
            raise
        except Exception:
            logging.error(
                f"[set-archive-files] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.get(
        "/files/download/{file_uid}",
        summary="Download generated file.",
        description="Downloads one of your files to your device.",
        tags=["Files"],
    )
    async def files_with_uid_to_download_generated_file(
        self, file_uid: UUID = Path(..., description="File UID.")
    ) -> StreamingResponse:
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        user_id = int(self.user["user_id"])
        try:
            generation_files = await get_generation_files(ctx, user_id, file_uids=[str(file_uid)])
            record = generation_files[0]
            content_type = mimetypes.guess_type(record["name"])[0] or "application/octet-stream"

            async def body() -> AsyncIterator[bytes]:
                async with APICaller(headers={"X-API-Key": UDIN_API_KEY}) as caller:
                    async with caller.stream("GET", record["path"]) as upstream:
                        upstream.raise_for_status()
                        async for chunk in upstream.aiter_bytes():
                            yield chunk

            logging.info(f"[download-file] user={user_id} file_uid={file_uid} streaming name={record['name']}")
            return StreamingResponse(
                body(),
                media_type=content_type,
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(record['name'])}"},
            )
        except BaseError:
            raise
        except Exception:
            logging.error(f"[download-file] user={user_id} file_uid={file_uid} failed\n{traceback.format_exc()}")
            raise ServiceError()

    @controller.patch(
        "/files/{project_uid}/favorite",
        summary="Set favourite files.",
        description="Marks the selected files as favorites, or removes them from favorites.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_uid_to_set_favorite_file(
        self, schema: SetFavoritedPayload, project_uid: UUID = Path(..., description="Project UID.")
    ) -> Response:
        response = Response()
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        user_id = int(self.user["user_id"])
        try:
            project = await get_project(ctx, project_uid)
            logging.info(
                f"[set-favourite-files] user={user_id} project_uid={project_uid} resolved project_id={project['id']}"
            )

            project_id = project["id"]
            requested_file_uids = [str(uid) for uid in schema.file_uids]
            favourited_files = []
            favouritable_files = []

            if schema.is_favorited is True:
                generation_files = await get_generation_files(ctx, user_id, project_id=project_id)
                favouritable_files = [record for record in generation_files if record["favourited_at"] is None]
                validated_file_uids = {record["file_uid"] for record in favouritable_files}
                logging.info(
                    f"[set-favourite-files] user={user_id} project_uid={project_uid} loaded {len(favouritable_files)} favouritable files"
                )
            else:
                favourited_files = await get_favourited_files(ctx, project_id, user_id)
                validated_file_uids = {record["file_uid"] for record in favourited_files}
                logging.info(
                    f"[set-favourite-files] user={user_id} project_uid={project_uid} loaded {len(favourited_files)} favourited files"
                )

            errors = {
                f"file_uids.{idx}": ["file_not_found"]
                for idx, uid in enumerate(requested_file_uids)
                if uid not in validated_file_uids
            }
            if errors:
                logging.warning(
                    f"[set-favourite-files] user={user_id} project_uid={project_uid} invalid file_uids={errors}"
                )
                raise DataNotFoundError(message="file_not_found", error=errors)

            favourited_at = local_time()
            rows = await query(
                self.db,
                DfEngineGenerationResults,
                filters=(DfEngineGenerationResults.uid.in_(requested_file_uids),),  # type: ignore
            )
            for row in rows:
                row.favourited_at = favourited_at if schema.is_favorited else None
                self.db.add(row)
            await self.db.flush()
            logging.info(
                f"[set-favourite-files] user={user_id} project_uid={project_uid} "
                f"updated {len(rows)} rows file_uids={requested_file_uids} is_favorited={schema.is_favorited}"
            )

            value = favourited_at if schema.is_favorited else None
            user_generation_files_key = cache_key.generation_files_result_list(user_id, project_id)
            cached_generation_files = await get_json(self.redis, user_generation_files_key)
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
                    f"[set-favourite-files] user={user_id} project_uid={project_uid} cache patched key={user_generation_files_key} file_uids={requested_file_uids}"
                )
            else:
                logging.info(
                    f"[set-favourite-files] user={user_id} project_uid={project_uid} cache miss key={user_generation_files_key}, skipped patch"
                )

            favourited_generations_key = cache_key.generation_files_favourited_list(user_id, project_id)
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
                    newly_favourited + await get_favourited_files(ctx, project_id, user_id),
                    key=lambda record: record["flag_favourited_at"],
                    reverse=True,
                )

            await set_json(self.redis, favourited_generations_key, favourited_files)
            logging.info(
                f"[set-favourite-files] user={user_id} project_uid={project_uid} cache updated key={favourited_generations_key} count={len(favourited_files)}"
            )

            response.data = favourited_files
        except BaseError:
            raise
        except Exception:
            logging.error(
                f"[set-favourite-files] user={user_id} project_uid={project_uid} failed\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.patch(
        "/files/set-main/{file_uid}",
        summary="Set a file as the main version.",
        description="Makes this file the featured version among its related versions.",
        status_code=status.HTTP_200_OK,
        tags=["Files"],
        response_model=Response,
    )
    async def files_with_uid_to_set_main_generation_file(
        self,
        file_uid: UUID = Path(..., description="Generation result UID to set as main."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            generation_variants = await get_generation_main_variants(ctx, file_uid, user_id)
            target = next((gen for gen in generation_variants if gen["file_uid"] == str(file_uid)), None)
            if target is None or target["is_main"] or not target["creator"] or target["creator"]["user_id"] != user_id:
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
                .values(is_main=DfEngineGenerationResults.uid == str(file_uid))
            )
            await self.db.flush()

            for uid in family_uids:
                await self.redis.delete(cache_key.generation_files_main_detail(uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variant_detail(uid))  # type: ignore
                await self.redis.delete(cache_key.generation_files_variants_detail(uid))  # type: ignore
            await delete_pattern(self.redis, cache_key.generation_files_main_list_pattern(generation.task_id))
            await delete_pattern(self.redis, cache_key.generation_files_references_picker_pattern(user_id))
            await self.redis.delete(cache_key.generation_files_result_list(user_id, generation.project_id))
            await self.redis.delete(cache_key.generation_files_archived_list(user_id, generation.project_id))
            await self.redis.delete(cache_key.generation_files_favourited_list(user_id, generation.project_id))

            response.data = await get_generation_main_file_detail(ctx, file_uid, user_id)
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
