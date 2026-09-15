import traceback
from typing import Any, Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.menu_management import MenuPayload
from services.mysql import query
from services.mysql.model import DfEngineFeatures, DfEngineMenuFeatureMappings, DfEngineMenus, DfEngineModelOptions
from services.mysql.model.df_engine_generations import DfEngineGenerations
from services.mysql.model.df_engine_generation_results import DfEngineGenerationResults
from services.mysql.model.df_engine_upload_files import DfEngineUploadFiles, UploadFileTypes
from services.redis import get_json, set_json, CacheKeys
from services.menu_management import MenuManagementService
from services.files import FilesService
from utils.formatter import format_size, format_datetime
from log import logging
from schemas.payload.generations import ImageGenerationsPayload
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils import local_time
from services.model_management import ModelManagement
from utils.serializer import serialize


class GenerationsController(CoreDependencies):
    @controller.get(
        "/models/{uid}",
        summary="Detail of a models.",
        description="Create propper description",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generations_with_uid_to_fetch_model_detail(self, uid: UUID = Path(description="Model UID.")) -> Response:
        response = Response()
        cache_key = CacheKeys()
        model_management_service = ModelManagement()
        try:
            model_option_details_cache_key = cache_key.model_option_details(uid)
            cached_model_option_details = await get_json(self.redis, model_option_details_cache_key)
            if cached_model_option_details:
                logging.info(f"user={self.user['user_id']} fetched detail model source=cache uid={uid}")
                response.data = cached_model_option_details
                return response

            result = await query(
                db=self.db,
                table=DfEngineModelOptions,
                filters=(DfEngineModelOptions.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if not result:
                raise DataNotFoundError(message="model_option_not_found")

            result = serialize(result)
            result = model_management_service.format(result)
            await set_json(self.redis, model_option_details_cache_key, result)

            logging.info(f"user={self.user['user_id']} fetched detail model source=db uid={uid}")
            response.data = result
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/references-picker/{task_uid}",
        summary="List a user's uploads and generation results for reference picking.",
        description=(
            "Cache-first. Returns five sections (Image Upload, Video Upload, Image Generation, "
            "Video Generation, Favorites), each scoped to the current user and to `task_uid`. "
            "Live (non-archived) generation results only; favourites are included regardless of "
            "archive state. A section whose query flag is `false` comes back with an empty `data` list."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_to_fetch_references_picker(
        self,
        task_uid: UUID = Path(..., description="Task UID."),
        image_uploads: bool = Query(True, description="Fetch uploaded image by user."),
        video_uploads: bool = Query(True, description="Fetch uploaded video by user."),
        image_generations: bool = Query(True, description="Fetch generated image by user."),
        video_generations: bool = Query(True, description="Fetch generated video by user."),
        favourites: bool = Query(True, description="Fetch favourited generation results by user."),
    ) -> Response:
        response = Response()
        file_service = FilesService()
        user_id = int(self.user["user_id"])
        try:
            project_task = await file_service.get_project_task(self.db, task_uid)
            task_id = project_task["id"]
            cache_key = CacheKeys().references_picker(
                user_id, task_id, image_uploads, video_uploads, image_generations, video_generations, favourites
            )
            cached = await get_json(self.redis, cache_key)
            if cached is not None:
                logging.info(f"user={user_id} listed reference picker source=cache")
                response.data = cached
                return response

            uploads_by_type: dict[str, list[dict[str, Any]]] = {"image": [], "video": []}
            upload_rows = await query(
                db=self.db,
                table=DfEngineUploadFiles,
                columns=(
                    DfEngineUploadFiles.uid,
                    DfEngineUploadFiles.path,
                    DfEngineUploadFiles.name,
                    DfEngineUploadFiles.size,
                    DfEngineUploadFiles.created_at,
                    DfEngineUploadFiles.updated_at,
                    DfEngineUploadFiles.type,
                ),
                filters=(
                    DfEngineUploadFiles.type.in_((UploadFileTypes.image, UploadFileTypes.video)),  # type: ignore
                    DfEngineUploadFiles.created_by == user_id,  # type: ignore
                    DfEngineUploadFiles.task_id == task_id,  # type: ignore
                ),
            )
            for row in upload_rows:
                uploads_by_type[row.type.value].append(
                    {
                        "uid": row.uid,
                        "path": file_service.file_url(row.path),
                        "name": row.name,
                        "size": format_size(row.size),
                        "created_at": format_datetime(row.created_at),
                        "updated_at": format_datetime(row.updated_at),
                        "type": row.type.value,
                    }
                )
            image_upload_files = uploads_by_type["image"] if image_uploads else []
            video_upload_files = uploads_by_type["video"] if video_uploads else []

            generations_by_kind: dict[str, list[dict[str, Any]]] = {"image": [], "video": []}
            favourite_files: list[dict[str, Any]] = []
            generation_rows = await query(
                db=self.db,
                table=DfEngineGenerationResults,
                columns=(
                    DfEngineGenerationResults.uid,
                    DfEngineGenerationResults.path,
                    DfEngineGenerationResults.name,
                    DfEngineGenerationResults.size,
                    DfEngineGenerationResults.created_at,
                    DfEngineGenerationResults.updated_at,
                    DfEngineGenerationResults.is_favourite,
                    DfEngineGenerations.kind,
                ),
                joins=((DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),),
                filters=(
                    DfEngineGenerations.created_by == user_id,  # type: ignore
                    DfEngineGenerations.task_id == task_id,  # type: ignore
                    DfEngineGenerationResults.archieved_at.is_(None),  # type: ignore
                    DfEngineGenerationResults.is_main.is_(True),  # type: ignore
                ),
            )
            for row in generation_rows:
                entry = {
                    "uid": row.uid,
                    "path": file_service.file_url(row.path),
                    "name": row.name,
                    "size": format_size(row.size),
                    "created_at": format_datetime(row.created_at),
                    "updated_at": format_datetime(row.updated_at),
                    "type": row.kind.value,
                }
                if row.kind.value in generations_by_kind:
                    generations_by_kind[row.kind.value].append(entry)
                if row.is_favourite:
                    favourite_files.append(entry)
            image_generation_files = generations_by_kind["image"] if image_generations else []
            video_generation_files = generations_by_kind["video"] if video_generations else []
            favourite_files = favourite_files if favourites else []

            data = [
                {"type": "Image Upload", "total_data": len(image_upload_files), "files": image_upload_files},
                {"type": "Video Upload", "total_data": len(video_upload_files), "files": video_upload_files},
                {
                    "type": "Image Generation",
                    "total_data": len(image_generation_files),
                    "files": image_generation_files,
                },
                {
                    "type": "Video Generation",
                    "total_data": len(video_generation_files),
                    "files": video_generation_files,
                },
                {"type": "Favorites", "total_data": len(favourite_files), "files": favourite_files},
            ]
            await set_json(self.redis, cache_key, data)
            logging.info(f"user={user_id} listed reference picker source=db")
            response.data = data
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/image-generations/{task_uid}",
        summary="Create image generation.",
        description="Create propper description",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_generate_an_image(
        self, schema: ImageGenerationsPayload, task_uid: UUID = Path(description="Task UID")
    ) -> Response:
        response = Response()
        try:
            pass
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/image-generations/{task_uid}/{file_uid}",
        summary="Create image generation.",
        description="Create propper description",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_generate_an_nested_image(
        self,
        schema: ImageGenerationsPayload,
        task_uid: UUID = Path(description="Task UID"),
        file_uid: UUID = Path(description="File UIDs."),
    ) -> Response:
        response = Response()
        try:
            pass
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
