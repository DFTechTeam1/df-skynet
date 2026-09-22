import traceback
from typing import Any, Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import delete, func, or_
from sqlalchemy.exc import IntegrityError
from apps.controller.core import CoreDependencies
from schemas.response import Response, PaginationResponse
from schemas.payload.menu_management import MenuPayload
from services.mysql import query
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    DfEngineModelOptions,
    DfEngineGenerations,
    DfEngineGenerationReconciliationIssues,
    DfEngineGenerationReferences,
    DfEngineGenerationResults,
    DfEngineGenerationUploads,
    DfEngineImageGenerationDetails,
    DfEngineUploadFileReferences,
    DfEngineUploadFiles,
    Employees,
    ProjectTasks,
    Users,
    DfEngineApiKeys,
    Projects,
)
from services.files import USD_TO_IDR_RATE
from services.mysql.model.df_engine_generations import GENERATION_KIND_ICON_COLOR, GenerationKinds, GenerationStatuses
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.redis import get_json, set_json, delete_pattern, CacheKeys
from services.menu_management import MenuManagementService
from services.files import FileCtx, FilesService
from utils.formatter import (
    format_udin_url,
    format_size,
    format_datetime,
    format_user_employees,
    format_idr,
    format_usd,
    format_employee_users,
)
from log import logging
from schemas.payload.generations import GenerationsPayload
from sqlalchemy.orm import load_only, selectinload
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils import local_time
from services.model_management import ModelManagement
from utils.serializer import serialize
from validations.project_tasks import get_project_task, assigned_task
from validations.employees import active_employee
from validations.openrouter.models import (
    validate_model_params,
    validate_references,
    validate_prompt_length,
    validate_features,
    merge_prompt,
    get_api_key,
    get_model,
    validate_api_key_limitation,
    get_team_pic,
)
from validations.prompt import rank_prompt
from parser.openrouter import parse_generation_payload
from services.api_caller import APICaller
from services.redis import CacheKeys
from apps.secret import OPENROUTER_BASE_URL, UDIN_API_KEY, UDIN_BASE_URL
from services.generations import attach_references
from services.tasks.image_generation import image_generation


class GenerationsController(CoreDependencies):
    @controller.get(
        "/models/{model_uid}",
        summary="Get model details.",
        description="Shows details about one AI model, like its name, provider, and price.",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generations_with_uid_to_fetch_model_detail(
        self, model_uid: UUID = Path(description="Model UID.")
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        model_management_service = ModelManagement()
        try:
            model_option_details_cache_key = cache_key.model_option_details(model_uid)
            cached_model_option_details = await get_json(self.redis, model_option_details_cache_key)
            if cached_model_option_details:
                logging.info(f"user={self.user['user_id']} fetched detail model source=cache uid={model_uid}")
                response.data = cached_model_option_details
                return response

            result = await query(
                db=self.db,
                table=DfEngineModelOptions,
                filters=(DfEngineModelOptions.uid == str(model_uid),),  # type: ignore
                fetch_one=True,
            )
            if not result:
                raise DataNotFoundError(message="model_option_not_found")

            result = serialize(result)
            result = model_management_service.format(result)
            await set_json(self.redis, model_option_details_cache_key, result)

            logging.info(f"user={self.user['user_id']} fetched detail model source=db uid={model_uid}")
            response.data = result
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/references-picker/{project_uid}",
        summary="Browse a project's files for picking references.",
        description=(
            "Shows your uploaded and generated files for one project, sorted into images, videos, "
            "and favorites, so you can pick one to reuse. You can search by file name."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_to_fetch_references_picker(
        self,
        project_uid: UUID = Path(..., description="Project UID."),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(
            default=20, ge=1, le=100, description="Number of records to return per page, per section."
        ),
        search: Optional[str] = Query(
            None, min_length=1, description="Search by file name (starts with). Leave empty to include all files."
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        user_id = int(self.user["user_id"])
        try:
            project = await query(
                db=self.db,
                table=Projects,
                filters=(Projects.uid == str(project_uid),),  # type: ignore
                fetch_one=True,
            )
            if not project:
                raise DataValidationError(message="project_not_found")

            project_id = project.id
            cache_key = cache_key.references_picker(user_id, project_id, page, itemsPerPage, search)
            cached = await get_json(self.redis, cache_key)
            if cached is not None:
                logging.info(f"user={user_id} listed reference picker source=cache")
                response.data = PaginationResponse(paginated=cached["data"], totalData=cached["total_data"])
                return response

            limit = itemsPerPage
            offset = (page - 1) * itemsPerPage

            upload_filters = (
                DfEngineUploadFiles.created_by == user_id,  # type: ignore
                DfEngineUploadFiles.project_id == project_id,  # type: ignore
            ) + ((DfEngineUploadFiles.name.ilike(f"{search}%"),) if search else ())  # type: ignore

            image_uploads_count = (
                await query(
                    db=self.db,
                    table=DfEngineUploadFiles,
                    columns=(func.count(DfEngineUploadFiles.id),),  # type: ignore
                    filters=(*upload_filters, DfEngineUploadFiles.type == UploadFileTypes.image),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            image_upload_rows = await query(
                db=self.db,
                table=DfEngineUploadFiles,
                options=(selectinload(DfEngineUploadFiles.task),),  # type: ignore
                filters=(*upload_filters, DfEngineUploadFiles.type == UploadFileTypes.image),  # type: ignore
                order_by=(DfEngineUploadFiles.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            image_upload_files = [
                {
                    "uid": row.uid,
                    "path": format_udin_url(row.path),
                    "name": row.name,
                    "source": "upload",
                    "size": format_size(row.size),
                    "created_at": format_datetime(row.created_at),
                    "updated_at": format_datetime(row.updated_at),
                    "type": row.type.value,
                    "task_name": row.task.name if row.task else None,
                }
                for row in image_upload_rows
            ]

            video_uploads_count = (
                await query(
                    db=self.db,
                    table=DfEngineUploadFiles,
                    columns=(func.count(DfEngineUploadFiles.id),),  # type: ignore
                    filters=(*upload_filters, DfEngineUploadFiles.type == UploadFileTypes.video),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            video_upload_rows = await query(
                db=self.db,
                table=DfEngineUploadFiles,
                options=(selectinload(DfEngineUploadFiles.task),),  # type: ignore
                filters=(*upload_filters, DfEngineUploadFiles.type == UploadFileTypes.video),  # type: ignore
                order_by=(DfEngineUploadFiles.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            video_upload_files = [
                {
                    "uid": row.uid,
                    "path": format_udin_url(row.path),
                    "name": row.name,
                    "source": "upload",
                    "size": format_size(row.size),
                    "created_at": format_datetime(row.created_at),
                    "updated_at": format_datetime(row.updated_at),
                    "type": row.type.value,
                    "task_name": row.task.name if row.task else None,
                }
                for row in video_upload_rows
            ]

            generation_filters = (
                DfEngineGenerations.created_by == user_id,  # type: ignore
                DfEngineGenerations.project_id == project_id,  # type: ignore
                DfEngineGenerationResults.archieved_at.is_(None),  # type: ignore
                DfEngineGenerationResults.is_main.is_(True),  # type: ignore
            ) + ((DfEngineGenerationResults.name.ilike(f"{search}%"),) if search else ())  # type: ignore
            generation_joins = (
                (DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id),
            )
            generation_options = (
                selectinload(DfEngineGenerationResults.generation).selectinload(DfEngineGenerations.task),  # type: ignore  # type: ignore
                selectinload(DfEngineGenerationResults.generation).selectinload(DfEngineGenerations.model_option),  # type: ignore  # type: ignore
            )

            image_generations_count = (
                await query(
                    db=self.db,
                    table=DfEngineGenerationResults,
                    columns=(func.count(DfEngineGenerationResults.id),),  # type: ignore
                    joins=generation_joins,
                    filters=(*generation_filters, DfEngineGenerations.kind == GenerationKinds.image),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            image_generation_rows = await query(
                db=self.db,
                table=DfEngineGenerationResults,
                options=generation_options,
                joins=generation_joins,
                filters=(*generation_filters, DfEngineGenerations.kind == GenerationKinds.image),  # type: ignore
                order_by=(DfEngineGenerationResults.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            image_generation_files = [
                {
                    "uid": row.uid,
                    "path": format_udin_url(row.path),
                    "name": row.name,
                    "source": "generated",
                    "size": format_size(row.size),
                    "created_at": format_datetime(row.created_at),
                    "updated_at": format_datetime(row.updated_at),
                    "type": row.generation.kind.value,
                    "task_name": row.generation.task.name if row.generation.task else None,
                    "prompt": row.generation.prompt,
                    "full_prompt": row.generation.full_prompt,
                    "model": row.generation.model_option.name if row.generation.model_option else None,
                }
                for row in image_generation_rows
            ]

            video_generations_count = (
                await query(
                    db=self.db,
                    table=DfEngineGenerationResults,
                    columns=(func.count(DfEngineGenerationResults.id),),  # type: ignore
                    joins=generation_joins,
                    filters=(*generation_filters, DfEngineGenerations.kind == GenerationKinds.video),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            video_generation_rows = await query(
                db=self.db,
                table=DfEngineGenerationResults,
                options=generation_options,
                joins=generation_joins,
                filters=(*generation_filters, DfEngineGenerations.kind == GenerationKinds.video),  # type: ignore
                order_by=(DfEngineGenerationResults.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            video_generation_files = [
                {
                    "uid": row.uid,
                    "path": format_udin_url(row.path),
                    "name": row.name,
                    "source": "generated",
                    "size": format_size(row.size),
                    "created_at": format_datetime(row.created_at),
                    "updated_at": format_datetime(row.updated_at),
                    "type": row.generation.kind.value,
                    "task_name": row.generation.task.name if row.generation.task else None,
                    "prompt": row.generation.prompt,
                    "full_prompt": row.generation.full_prompt,
                    "model": row.generation.model_option.name if row.generation.model_option else None,
                }
                for row in video_generation_rows
            ]

            favourites_count = (
                await query(
                    db=self.db,
                    table=DfEngineGenerationResults,
                    columns=(func.count(DfEngineGenerationResults.id),),  # type: ignore
                    joins=generation_joins,
                    filters=(*generation_filters, DfEngineGenerationResults.is_favourite.is_(True)),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            favourite_rows = await query(
                db=self.db,
                table=DfEngineGenerationResults,
                options=generation_options,
                joins=generation_joins,
                filters=(*generation_filters, DfEngineGenerationResults.is_favourite.is_(True)),  # type: ignore
                order_by=(DfEngineGenerationResults.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            favourite_files = [
                {
                    "uid": row.uid,
                    "path": format_udin_url(row.path),
                    "name": row.name,
                    "source": "generated",
                    "size": format_size(row.size),
                    "created_at": format_datetime(row.created_at),
                    "updated_at": format_datetime(row.updated_at),
                    "type": row.generation.kind.value,
                    "task_name": row.generation.task.name if row.generation.task else None,
                    "prompt": row.generation.prompt,
                    "full_prompt": row.generation.full_prompt,
                    "model": row.generation.model_option.name if row.generation.model_option else None,
                }
                for row in favourite_rows
            ]

            data = [
                {"type": "Image Uploads", "total_data": image_uploads_count, "files": image_upload_files},
                {"type": "Video Uploads", "total_data": video_uploads_count, "files": video_upload_files},
                {"type": "Image Generations", "total_data": image_generations_count, "files": image_generation_files},
                {"type": "Video Generations", "total_data": video_generations_count, "files": video_generation_files},
                {"type": "Favorites", "total_data": favourites_count, "files": favourite_files},
                {"type": "Elements", "total_data": 0, "files": []},
            ]
            total_data = max(
                image_uploads_count,
                video_uploads_count,
                image_generations_count,
                video_generations_count,
                favourites_count,
            )
            await set_json(self.redis, cache_key, {"data": data, "total_data": total_data})
            logging.info(f"user={user_id} listed reference picker source=db")
            response.data = PaginationResponse(paginated=data, totalData=total_data)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/references-picker",
        summary="Browse every project's files for picking references.",
        description=(
            "Shows your uploaded and generated files across all your projects, grouped by project "
            "and task, so you can pick one to reuse. You can search by project or file name."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_to_fetch_global_references_picker(
        self,
        project_name: Optional[str] = Query(
            None, min_length=1, description="Search by project name (starts with). Leave empty to include all projects."
        ),
        file_name: Optional[str] = Query(
            None, min_length=1, description="Search by file name (starts with). Leave empty to include all files."
        ),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(
            default=20, ge=1, le=100, description="Number of records to return per page, per section."
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        user_id = int(self.user["user_id"])
        try:
            cache_key = cache_key.global_references_picker(user_id, project_name, file_name, page, itemsPerPage)
            cached = await get_json(self.redis, cache_key)
            if cached is not None:
                logging.info(f"user={user_id} listed global reference picker source=cache")
                response.data = PaginationResponse(paginated=cached["data"], totalData=cached["total_data"])
                return response

            limit = itemsPerPage
            offset = (page - 1) * itemsPerPage

            upload_filters = [DfEngineUploadFiles.created_by == user_id]  # type: ignore
            upload_joins = ()
            if project_name:
                upload_joins = ((Projects, DfEngineUploadFiles.project_id == Projects.id),)
                upload_filters.append(Projects.name.ilike(f"{project_name}%"))  # type: ignore
            if file_name:
                upload_filters.append(DfEngineUploadFiles.name.ilike(f"{file_name}%"))  # type: ignore
            upload_filters = tuple(upload_filters)
            upload_options = (
                selectinload(DfEngineUploadFiles.project),  # type: ignore
                selectinload(DfEngineUploadFiles.task),  # type: ignore
            )

            image_uploads_count = (
                await query(
                    db=self.db,
                    table=DfEngineUploadFiles,
                    columns=(func.count(DfEngineUploadFiles.id),),  # type: ignore
                    joins=upload_joins,
                    filters=(*upload_filters, DfEngineUploadFiles.type == UploadFileTypes.image),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            image_upload_rows = await query(
                db=self.db,
                table=DfEngineUploadFiles,
                options=upload_options,
                joins=upload_joins,
                filters=(*upload_filters, DfEngineUploadFiles.type == UploadFileTypes.image),  # type: ignore
                order_by=(DfEngineUploadFiles.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            image_upload_projects = {}
            for row in image_upload_rows:
                project_entry = image_upload_projects.setdefault(
                    row.project_id, {"name": row.project.name if row.project else None, "tasks": {}}
                )
                task_entry = project_entry["tasks"].setdefault(
                    row.task_id, {"task": row.task.name if row.task else None, "files": []}
                )
                task_entry["files"].append(
                    {
                        "uid": row.uid,
                        "path": format_udin_url(row.path),
                        "name": row.name,
                        "source": "upload",
                        "size": format_size(row.size),
                        "created_at": format_datetime(row.created_at),
                        "updated_at": format_datetime(row.updated_at),
                        "type": row.type.value,
                    }
                )
            image_upload_projects = [
                {"name": p["name"], "tasks": list(p["tasks"].values())} for p in image_upload_projects.values()
            ]

            video_uploads_count = (
                await query(
                    db=self.db,
                    table=DfEngineUploadFiles,
                    columns=(func.count(DfEngineUploadFiles.id),),  # type: ignore
                    joins=upload_joins,
                    filters=(*upload_filters, DfEngineUploadFiles.type == UploadFileTypes.video),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            video_upload_rows = await query(
                db=self.db,
                table=DfEngineUploadFiles,
                options=upload_options,
                joins=upload_joins,
                filters=(*upload_filters, DfEngineUploadFiles.type == UploadFileTypes.video),  # type: ignore
                order_by=(DfEngineUploadFiles.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            video_upload_projects = {}
            for row in video_upload_rows:
                project_entry = video_upload_projects.setdefault(
                    row.project_id, {"name": row.project.name if row.project else None, "tasks": {}}
                )
                task_entry = project_entry["tasks"].setdefault(
                    row.task_id, {"task": row.task.name if row.task else None, "files": []}
                )
                task_entry["files"].append(
                    {
                        "uid": row.uid,
                        "path": format_udin_url(row.path),
                        "name": row.name,
                        "source": "upload",
                        "size": format_size(row.size),
                        "created_at": format_datetime(row.created_at),
                        "updated_at": format_datetime(row.updated_at),
                        "type": row.type.value,
                    }
                )
            video_upload_projects = [
                {"name": p["name"], "tasks": list(p["tasks"].values())} for p in video_upload_projects.values()
            ]

            generation_filters = [
                DfEngineGenerations.created_by == user_id,  # type: ignore
                DfEngineGenerationResults.archieved_at.is_(None),  # type: ignore
                DfEngineGenerationResults.is_main.is_(True),  # type: ignore
            ]
            generation_joins = [
                (DfEngineGenerations, DfEngineGenerationResults.generation_id == DfEngineGenerations.id)
            ]
            if project_name:
                generation_joins.append((Projects, DfEngineGenerations.project_id == Projects.id))  # type: ignore
                generation_filters.append(Projects.name.ilike(f"{project_name}%"))  # type: ignore
            if file_name:
                generation_filters.append(DfEngineGenerationResults.name.ilike(f"{file_name}%"))  # type: ignore
            generation_filters = tuple(generation_filters)
            generation_joins = tuple(generation_joins)
            generation_options = (
                selectinload(DfEngineGenerationResults.generation).selectinload(DfEngineGenerations.project),  # type: ignore
                selectinload(DfEngineGenerationResults.generation).selectinload(DfEngineGenerations.task),  # type: ignore
                selectinload(DfEngineGenerationResults.generation).selectinload(DfEngineGenerations.model_option),  # type: ignore  # type: ignore
            )

            image_generations_count = (
                await query(
                    db=self.db,
                    table=DfEngineGenerationResults,
                    columns=(func.count(DfEngineGenerationResults.id),),  # type: ignore
                    joins=generation_joins,
                    filters=(*generation_filters, DfEngineGenerations.kind == GenerationKinds.image),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            image_generation_rows = await query(
                db=self.db,
                table=DfEngineGenerationResults,
                options=generation_options,
                joins=generation_joins,
                filters=(*generation_filters, DfEngineGenerations.kind == GenerationKinds.image),  # type: ignore
                order_by=(DfEngineGenerationResults.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            image_generation_projects = {}
            for row in image_generation_rows:
                project_entry = image_generation_projects.setdefault(
                    row.generation.project_id if row.generation else None,
                    {
                        "name": row.generation.project.name if row.generation and row.generation.project else None,
                        "tasks": {},
                    },
                )
                task_entry = project_entry["tasks"].setdefault(
                    row.generation.task_id if row.generation else None,
                    {"task": row.generation.task.name if row.generation and row.generation.task else None, "files": []},
                )
                task_entry["files"].append(
                    {
                        "uid": row.uid,
                        "path": format_udin_url(row.path),
                        "name": row.name,
                        "source": "generated",
                        "size": format_size(row.size),
                        "created_at": format_datetime(row.created_at),
                        "updated_at": format_datetime(row.updated_at),
                        "type": row.generation.kind.value,
                        "prompt": row.generation.prompt,
                        "full_prompt": row.generation.full_prompt,
                        "model": row.generation.model_option.name if row.generation.model_option else None,
                    }
                )
            image_generation_projects = [
                {"name": p["name"], "tasks": list(p["tasks"].values())} for p in image_generation_projects.values()
            ]

            video_generations_count = (
                await query(
                    db=self.db,
                    table=DfEngineGenerationResults,
                    columns=(func.count(DfEngineGenerationResults.id),),  # type: ignore
                    joins=generation_joins,
                    filters=(*generation_filters, DfEngineGenerations.kind == GenerationKinds.video),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            video_generation_rows = await query(
                db=self.db,
                table=DfEngineGenerationResults,
                options=generation_options,
                joins=generation_joins,
                filters=(*generation_filters, DfEngineGenerations.kind == GenerationKinds.video),  # type: ignore
                order_by=(DfEngineGenerationResults.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            video_generation_projects = {}
            for row in video_generation_rows:
                project_entry = video_generation_projects.setdefault(
                    row.generation.project_id if row.generation else None,
                    {
                        "name": row.generation.project.name if row.generation and row.generation.project else None,
                        "tasks": {},
                    },
                )
                task_entry = project_entry["tasks"].setdefault(
                    row.generation.task_id if row.generation else None,
                    {"task": row.generation.task.name if row.generation and row.generation.task else None, "files": []},
                )
                task_entry["files"].append(
                    {
                        "uid": row.uid,
                        "path": format_udin_url(row.path),
                        "name": row.name,
                        "source": "generated",
                        "size": format_size(row.size),
                        "created_at": format_datetime(row.created_at),
                        "updated_at": format_datetime(row.updated_at),
                        "type": row.generation.kind.value,
                        "prompt": row.generation.prompt,
                        "full_prompt": row.generation.full_prompt,
                        "model": row.generation.model_option.name if row.generation.model_option else None,
                    }
                )
            video_generation_projects = [
                {"name": p["name"], "tasks": list(p["tasks"].values())} for p in video_generation_projects.values()
            ]

            favourites_count = (
                await query(
                    db=self.db,
                    table=DfEngineGenerationResults,
                    columns=(func.count(DfEngineGenerationResults.id),),  # type: ignore
                    joins=generation_joins,
                    filters=(*generation_filters, DfEngineGenerationResults.is_favourite.is_(True)),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )
            favourite_rows = await query(
                db=self.db,
                table=DfEngineGenerationResults,
                options=generation_options,
                joins=generation_joins,
                filters=(*generation_filters, DfEngineGenerationResults.is_favourite.is_(True)),  # type: ignore
                order_by=(DfEngineGenerationResults.created_at.desc(),),  # type: ignore
                limit=limit,
                offset=offset,
            )
            favourite_projects = {}
            for row in favourite_rows:
                project_entry = favourite_projects.setdefault(
                    row.generation.project_id if row.generation else None,
                    {
                        "name": row.generation.project.name if row.generation and row.generation.project else None,
                        "tasks": {},
                    },
                )
                task_entry = project_entry["tasks"].setdefault(
                    row.generation.task_id if row.generation else None,
                    {"task": row.generation.task.name if row.generation and row.generation.task else None, "files": []},
                )
                task_entry["files"].append(
                    {
                        "uid": row.uid,
                        "path": format_udin_url(row.path),
                        "name": row.name,
                        "source": "generated",
                        "size": format_size(row.size),
                        "created_at": format_datetime(row.created_at),
                        "updated_at": format_datetime(row.updated_at),
                        "type": row.generation.kind.value,
                        "prompt": row.generation.prompt,
                        "full_prompt": row.generation.full_prompt,
                        "model": row.generation.model_option.name if row.generation.model_option else None,
                    }
                )
            favourite_projects = [
                {"name": p["name"], "tasks": list(p["tasks"].values())} for p in favourite_projects.values()
            ]

            data = [
                {"type": "Image Uploads", "total_data": image_uploads_count, "projects": image_upload_projects},
                {"type": "Video Uploads", "total_data": video_uploads_count, "projects": video_upload_projects},
                {
                    "type": "Image Generations",
                    "total_data": image_generations_count,
                    "projects": image_generation_projects,
                },
                {
                    "type": "Video Generations",
                    "total_data": video_generations_count,
                    "projects": video_generation_projects,
                },
                {"type": "Favorites", "total_data": favourites_count, "projects": favourite_projects},
                {"type": "Elements", "total_data": 0, "projects": []},
            ]
            total_data = max(
                image_uploads_count,
                video_uploads_count,
                image_generations_count,
                video_generations_count,
                favourites_count,
            )
            await set_json(self.redis, cache_key, {"data": data, "total_data": total_data})
            logging.info(f"user={user_id} listed global reference picker source=db")
            response.data = PaginationResponse(paginated=data, totalData=total_data)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/generations/{task_uid}",
        summary="Generate an image or video.",
        description="Creates a new image or video from your prompt using AI.",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_generate_an_image_or_video(
        self, schema: GenerationsPayload, task_uid: UUID = Path(description="Task UID")
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        user_id = int(self.user["user_id"])
        try:
            # Will be enabled later
            """Employee validations"""
            task = await get_project_task(str(task_uid))
            # await active_employee(user_id)
            # await assigned_task(task['id'], employee['id'])
            task_id = task["id"]
            project_id = task["project"]["id"]

            """Menu and Feature validations"""
            prompt_templates, menu_id, feature_id = await validate_features(
                self.db, str(schema.menu_uid), str(schema.feature_uid)
            )

            """Prompt length char validations"""
            await validate_prompt_length(self.db, schema.prompt, task_id)

            """Prompt merging with feature prompt templates"""
            final_prompt = merge_prompt(schema.prompt, prompt_templates)

            """Model validations"""
            model = await get_model(self.db, schema.type, str(schema.model_uid))
            references = [ref.model_dump() for ref in schema.references]
            await validate_model_params(self.db, schema.type, str(schema.model_uid), references, schema.parameter)
            valid_references = await validate_references(self.db, references, user_id, task_id)

            """API Key validations"""
            # employee_pic = await get_team_pic(self.db, user_id) # User will be used openrouter API Key from its PIC.
            pic_id = 3  # Rudhi as example
            api_key = await get_api_key(self.db, pic_id)  # will be replaced with employee_pic['id]
            api_key_id = api_key["id"]
            await validate_api_key_limitation(self.db, project_id, api_key_id)

            """Prompt ranking validation"""
            await rank_prompt(schema.prompt, model["model_id"], api_key["key"], schema.type)

            """Initialize insert generation record"""
            generation = DfEngineGenerations(
                kind=schema.type,  # type: ignore
                model_id=model["id"],
                menu_id=menu_id,
                feature_id=feature_id,
                sourceable_id=api_key_id,
                sourceable_type=DfEngineApiKeys.__name__,
                project_id=project_id,
                task_id=task_id,
                prompt=schema.prompt,
                full_prompt=final_prompt,
                created_by=user_id,
            )
            self.db.add(generation)
            await self.db.flush()

            """Insert reference records"""
            await attach_references(self.db, generation.id, valid_references)

            match schema.type:
                case "image":
                    payload = parse_generation_payload(
                        schema.type,
                        model["model_id"],
                        final_prompt,
                        schema.parameter,
                        [ref["url"] for ref in valid_references],
                    )
                    self.db.add(DfEngineImageGenerationDetails(generation_id=generation.id, parameter=payload))
                    await self.db.commit()
                    image_generation.delay(  # type:ignore
                        generation.id,
                        user_id,
                        headers={"Authorization": f"Bearer {api_key['key']}"},
                        payload=payload,
                    )
                case _:
                    return response

            await delete_pattern(self.redis, cache_key.user_galleries_pattern(user_id))
            await delete_pattern(self.redis, cache_key.references_picker_pattern(user_id))
            await delete_pattern(self.redis, cache_key.global_references_picker_pattern(user_id))

            record = await query(
                db=self.db,
                table=DfEngineGenerations,
                joins=(
                    (
                        DfEngineGenerationResults,
                        DfEngineGenerationResults.generation_id == DfEngineGenerations.id,
                        True,
                    ),
                ),
                options=(
                    selectinload(DfEngineGenerations.model_option),  # type: ignore
                    selectinload(DfEngineGenerations.result).selectinload(DfEngineGenerationResults.children),  # type: ignore  # type: ignore
                ),
                filters=(DfEngineGenerations.id == generation.id,),
                fetch_one=True,
            )
            record = serialize(record)
            model = record.get("model_option", None)
            result = record.get("result", None)

            record["created_at"] = format_datetime(record["created_at"])
            record["generation_uid"] = record.pop("uid", None)
            record["file_uid"] = result.get("uid") if result else None
            record["type"] = record.pop("kind", None)
            record["cost_idr"] = format_idr(record["cost"], USD_TO_IDR_RATE)
            record["cost_usd"] = format_usd(record["cost"])
            record["model"] = model.get("name") if model else None
            record["file_id"] = result.get("id") if result else None
            record["parent_id"] = result.get("parent_id") if result else None
            record["md5"] = result.get("md5") if result else None
            record["name"] = result.get("name") if result else None
            record["path"] = format_udin_url(result.get("path")) if result else None
            record["size"] = format_size(result.get("size")) if result else None
            record["is_favourite"] = result.get("is_favourite") if result else None
            record["is_main"] = result.get("is_main") if result else None
            record["version"] = result.get("version") if result else None
            record["source"] = "generated"
            record["total_variant"] = 1
            record["action"] = {
                "can_fetch_detail": result is not None,
                "can_use_as_reference": result is not None,
                "can_set_main": record["is_main"] is False,
                "can_archieve": result is not None and record["is_main"] is False,
                "can_favorited": record["is_favourite"] is False,
                "can_unfavorited": record["is_favourite"] is True,
                "can_download": record["created_by"] == int(self.user["user_id"]) and result is not None,
            }
            record.pop("id", None)
            record.pop("model_option", None)
            record.pop("model_id", None)
            record.pop("cost", None)
            record.pop("file_id", None)
            record.pop("menu_id", None)
            record.pop("feature_id", None)
            record.pop("sourceable_id", None)
            record.pop("sourceable_type", None)
            record.pop("project_id", None)
            record.pop("task_id", None)
            record.pop("response", None)
            record.pop("status_code", None)
            record.pop("token_usage", None)
            record.pop("created_by", None)
            record.pop("archieved_at", None)
            record.pop("result", None)

            logging.info(f"user={self.user['user_id']} created generation source=db task_uid={task_uid}")
            response.data = record
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/user-galleries/{task_uid}",
        summary="List a user's generated image and video galleries.",
        description=(
            "Shows the images and videos you've generated for this task. Older versions of the "
            "same image or video are grouped underneath the current one. You can search by file "
            "name or prompt."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_fetch_all_generation_galleries(
        self,
        task_uid: UUID = Path(description="Task UID"),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=20, ge=1, le=100, description="Number of records to return per page."),
        search: Optional[str] = Query(
            None, min_length=1, description="Search by file name or prompt (starts with). Leave empty to include all."
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        user_id = self.user["user_id"]
        try:
            project_task = await get_project_task(str(task_uid))
            task_id = project_task["id"]
            user_galleries_key = cache_key.user_galleries(user_id, task_id, page, itemsPerPage, search)
            cached = await get_json(self.redis, user_galleries_key)
            if cached is not None:
                logging.info(f"user={self.user['user_id']} listed user galleries source=cache task_uid={task_uid}")
                response.data = PaginationResponse(paginated=cached["data"], totalData=cached["total_data"])
                return response

            gallery_filters = (
                DfEngineGenerations.created_by == self.user["user_id"],
                DfEngineGenerations.task_id == project_task["id"],
                or_(DfEngineGenerationResults.is_main.is_(True), DfEngineGenerationResults.id.is_(None)),  # type: ignore
                DfEngineGenerationResults.archieved_at.is_(None),  # type: ignore
            ) + (
                (
                    or_(
                        DfEngineGenerationResults.name.ilike(f"{search}%"),
                        DfEngineGenerations.prompt.ilike(f"{search}%"),
                    ),
                )  # type: ignore
                if search
                else ()
            )
            gallery_joins = (
                (DfEngineGenerationResults, DfEngineGenerationResults.generation_id == DfEngineGenerations.id, True),
            )

            total_data = (
                await query(
                    db=self.db,
                    table=DfEngineGenerations,
                    columns=(func.count(DfEngineGenerations.id),),  # type: ignore
                    joins=gallery_joins,
                    filters=gallery_filters,
                    fetch_one=True,
                )
                or 0
            )

            records = await query(
                db=self.db,
                table=DfEngineGenerations,
                joins=gallery_joins,
                options=(
                    selectinload(DfEngineGenerations.model_option),  # type: ignore
                    selectinload(DfEngineGenerations.result).selectinload(DfEngineGenerationResults.children),  # type: ignore  # type: ignore
                ),
                filters=gallery_filters,
                order_by=(DfEngineGenerations.created_at.desc(),),  # type: ignore
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
            )
            records = [serialize(record) for record in records]
            for record in records:
                model = record.get("model_option", None)
                result = record.get("result", None)
                record["created_at"] = format_datetime(record["created_at"])
                record["generation_uid"] = record.pop("uid", None)
                record["file_uid"] = result.get("uid") if result else None
                record["type"] = record.pop("kind", None)
                record["cost_idr"] = format_idr(record["cost"], USD_TO_IDR_RATE)
                record["cost_usd"] = format_usd(record["cost"])
                record["model"] = model.get("name") if model else None
                record["file_id"] = result.get("id") if result else None
                record["parent_id"] = result.get("parent_id") if result else None
                record["md5"] = result.get("md5") if result else None
                record["name"] = result.get("name") if result else None
                record["path"] = format_udin_url(result.get("path")) if result else None
                record["size"] = format_size(result.get("size")) if result else None
                record["is_favourite"] = result.get("is_favourite") if result else None
                record["is_main"] = result.get("is_main") if result else None
                record["version"] = result.get("version") if result else None
                record["source"] = "generated"
                children = result.get("children") or [] if result else []
                variants = [
                    {
                        "file_uid": child.get("uid"),
                        "parent_id": child.get("parent_id"),
                        "md5": child.get("md5"),
                        "name": child.get("name"),
                        "path": format_udin_url(child.get("path")),
                        "size": format_size(child.get("size")),
                        "is_favourite": child.get("is_favourite"),
                        "is_main": child.get("is_main"),
                        "version": child.get("version"),
                        "archieved_at": format_datetime(child.get("archieved_at")),
                    }
                    for child in children
                ]
                if result:
                    variants.append(
                        {
                            "file_uid": record["file_uid"],
                            "parent_id": record["parent_id"],
                            "md5": record["md5"],
                            "name": record["name"],
                            "path": record["path"],
                            "size": record["size"],
                            "is_favourite": record["is_favourite"],
                            "is_main": record["is_main"],
                            "version": record["version"],
                        }
                    )
                record["total_variant"] = len(variants)
                record["variants"] = sorted(variants, key=lambda v: v["version"] or 0)
                record["action"] = {
                    "can_fetch_detail": result is not None,
                    "can_use_as_reference": result is not None,
                    "can_set_main": record["is_main"] is False,
                    "can_archieve": result is not None and record["is_main"] is False,
                    "can_favorited": record["is_favourite"] is False,
                    "can_unfavorited": record["is_favourite"] is True,
                    "can_download": record["created_by"] == int(self.user["user_id"]) and result is not None,
                }

                record.pop("id", None)
                record.pop("model_option", None)
                record.pop("model_id", None)
                record.pop("cost", None)
                record.pop("file_id", None)
                record.pop("menu_id", None)
                record.pop("feature_id", None)
                record.pop("sourceable_id", None)
                record.pop("sourceable_type", None)
                record.pop("project_id", None)
                record.pop("task_id", None)
                record.pop("response", None)
                record.pop("status_code", None)
                record.pop("token_usage", None)
                record.pop("created_by", None)
                record.pop("archieved_at", None)
                record.pop("result", None)
                record.pop("variants", None)

            await set_json(self.redis, user_galleries_key, {"data": records, "total_data": total_data})
            logging.info(f"user={user_id} listed user galleries source=db task_uid={task_uid}")
            response.data = PaginationResponse(paginated=records, totalData=total_data)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/user-galleries/generated/{file_uid}",
        summary="Get a generated file's details.",
        description=("Shows the details of one generated image or video, including its other versions if it has any."),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_fetch_generated_file_details(
        self, file_uid: UUID = Path(description="Generation file UID.")
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        user_id = int(self.user["user_id"])
        try:
            detail_key = cache_key.generation_file_detail(user_id, str(file_uid))
            cached = await get_json(self.redis, detail_key)
            if cached is not None:
                logging.info(f"user={user_id} fetched generated file detail source=cache file_uid={file_uid}")
                response.data = cached
                return response

            own_generation = selectinload(DfEngineGenerationResults.generation).selectinload(  # type: ignore
                DfEngineGenerations.model_option  # type: ignore
            )
            target = await query(
                db=self.db,
                table=DfEngineGenerationResults,
                options=(
                    own_generation,
                    selectinload(DfEngineGenerationResults.children)
                    .selectinload(  # type: ignore
                        DfEngineGenerationResults.generation  # type: ignore
                    )
                    .selectinload(DfEngineGenerations.model_option),  # type: ignore
                    selectinload(DfEngineGenerationResults.parent)
                    .selectinload(  # type: ignore
                        DfEngineGenerationResults.generation  # type: ignore
                    )
                    .selectinload(DfEngineGenerations.model_option),  # type: ignore
                    selectinload(DfEngineGenerationResults.parent)
                    .selectinload(  # type: ignore
                        DfEngineGenerationResults.children  # type: ignore
                    )
                    .selectinload(DfEngineGenerationResults.generation)
                    .selectinload(  # type: ignore
                        DfEngineGenerations.model_option  # type: ignore
                    ),
                ),
                filters=(
                    DfEngineGenerationResults.uid == str(file_uid),  # type: ignore
                    DfEngineGenerationResults.created_by == user_id,  # type: ignore
                ),
                fetch_one=True,
            )
            if not target:
                raise DataNotFoundError(message="generation_file_not_found")

            root = target.parent if target.parent_id else target
            family_rows = [row for row in [root, *root.children] if row.created_by == user_id]

            target_entry: Optional[dict[str, Any]] = None
            variants: list[dict[str, Any]] = []
            for row in family_rows:
                generation = row.generation
                model = generation.model_option if generation else None
                entry = {
                    "created_at": format_datetime(row.created_at),
                    "prompt": generation.prompt if generation else None,
                    "full_prompt": generation.full_prompt if generation else None,
                    "status": generation.status.value if generation else None,
                    "generation_uid": generation.uid if generation else None,
                    "file_uid": row.uid,
                    "type": generation.kind.value if generation else None,
                    "cost_idr": format_idr(generation.cost, USD_TO_IDR_RATE) if generation else None,
                    "cost_usd": format_usd(generation.cost) if generation else None,
                    "model": model.name if model else None,
                    "md5": row.md5,
                    "name": row.name,
                    "path": format_udin_url(row.path),
                    "size": format_size(row.size),
                    "is_favourite": row.is_favourite,
                    "is_main": row.is_main,
                    "version": row.version,
                    "archieved_at": format_datetime(row.archieved_at),
                    "source": "generated",
                    "action": {
                        "can_fetch_detail": True,
                        "can_use_as_reference": True,
                        "can_set_main": row.is_main is False,
                        "can_archieve": row.is_main is False,
                        "can_favorited": row.is_favourite is False,
                        "can_unfavorited": row.is_favourite is True,
                        "can_download": row.created_by == user_id,
                    },
                }
                if row.uid == target.uid:
                    target_entry = entry
                variants.append(entry)
            variants.sort(key=lambda v: v["version"] or 0)
            if target_entry is None:
                raise DataNotFoundError(message="generation_file_not_found")

            data = dict(target_entry)
            action = data.pop("action")
            data["total_variant"] = len(variants)
            if target.version == 1 and len(variants) > 1:
                data["variants"] = variants
            data["action"] = action

            await set_json(self.redis, detail_key, data)
            logging.info(f"user={user_id} fetched generated file detail source=db file_uid={file_uid}")
            response.data = data
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
