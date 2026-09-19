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
)
from services.files import USD_TO_IDR_RATE
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.redis import get_json, set_json, CacheKeys
from services.menu_management import MenuManagementService
from services.files import FileCtx, FilesService
from utils.formatter import format_udin_url, format_size, format_datetime, format_user_employees, format_idr
from log import logging
from schemas.payload.generations import GenerationsPayload
from sqlalchemy.orm import selectinload
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
)
from parser.openrouter import parse_generation_payload
from services.api_caller import APICaller
from services.redis import CacheKeys
from apps.secret import OPENROUTER_BASE_URL, UDIN_API_KEY, UDIN_BASE_URL
from services.generations import attach_references


class GenerationsController(CoreDependencies):
    @controller.get(
        "/models/{model_uid}",
        summary="Detail of a model.",
        description=(
            "Returns everything about one AI model available on the platform: its name, "
            "provider, pricing, and whether it's currently enabled or set as the default. "
            "Cache-first, so repeat lookups are fast."
        ),
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
                        "path": format_udin_url(row.path),
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
                    "path": format_udin_url(row.path),
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
        "/generations/{task_uid}",
        summary="Generate an image or video.",
        description=(
            "Submits a prompt and asks the AI model to generate a brand-new image for this task. "
            "The result becomes the main image for its own new generation, ready to preview, "
            "archive, favorite, or use as the reference for further generations."
        ),
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
            # Add get pic team here to be passed as args to filter API Key down bellow. Currently value is set to static with Rudhi's API keys
            task_id = task["id"]
            project_id = task["project"]["id"]

            """Menu and Feature validations"""
            prompt_templates, menu_id, feature_id = await validate_features(
                str(schema.menu_uid), str(schema.feature_uid)
            )

            """Prompt length char validations"""
            await validate_prompt_length(schema.prompt, task_id)

            """Prompt merging with feature prompt templates"""
            final_prompt = merge_prompt(schema.prompt, prompt_templates)

            """Model validations"""
            model = await get_model(schema.type, str(schema.model_uid))
            references = [ref.model_dump() for ref in schema.references]
            await validate_model_params(schema.type, str(schema.model_uid), references, schema.parameter)
            valid_references = await validate_references(references, user_id, task_id)

            """API Key validations"""
            # User will be used openrouter API Key from its PIC.
            pic_id = 3  # Rudhi as example
            api_key = await get_api_key(pic_id)
            api_key_id = api_key["id"]
            await validate_api_key_limitation(project_id, api_key_id)

            # Initialize insert generation record
            generation = DfEngineGenerations(
                kind=schema.type,  # type: ignore
                model_id=model["id"],
                menu_id=menu_id,
                feature_id=feature_id,
                sourceable_id=api_key_id,
                sourceable_type=type(api_key).__name__,
                project_id=project_id,
                task_id=task_id,
                prompt=schema.prompt,
                full_prompt=final_prompt,
                created_by=user_id,
            )
            self.db.add(generation)
            await self.db.flush()

            # Insert reference records
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
                    # self.db.add(DfEngineImageGenerationDetails(generation_id=generation.id, parameter=payload))
                    response.data = valid_references
                case "image_edit":
                    # Will be build later
                    # payload = parse_generation_payload(
                    #     schema.type, model["model_id"], final_prompt, schema.parameter, [ref["url"] for ref in valid_references]
                    # )
                    # self.db.add(DfEngineImageGenerationDetails(
                    #     generation_id=generation.id,
                    #     parameter=payload,
                    #     x_max=schema.x_max,
                    #     x_min=schema.x_min,
                    #     y_max=schema.y_max,
                    #     y_min=schema.y_min
                    # ))
                    return response
                case _:
                    # Will be build later
                    return response

            await self.redis.delete(cache_key.user_galleries(self.user["user_id"], task["id"]))

            generation_result = await query(
                db=self.db,
                table=DfEngineGenerations,
                options=(
                    selectinload(DfEngineGenerations.result),  # type: ignore
                    selectinload(DfEngineGenerations.api_key),  # type: ignore
                    selectinload(DfEngineGenerations.api_key_snapshot),  # type: ignore
                    selectinload(DfEngineGenerations.model_option),  # type: ignore
                ),
                filters=(DfEngineGenerations.id == generation.id,),
                fetch_one=True,
            )
            response.data = serialize(generation_result)

            # """OpenRouter call"""
            # api_caller = APICaller(headers={"Authorization": f"Bearer {api_key.key}"})
            # logging.info(f"user={user_id} calling openrouter task_uid={task_uid} model={model['model_id']}")
            # openrouter_response = await api_caller.openrouter(
            #     "POST", f"{OPENROUTER_BASE_URL}/images", user_id=user_id, json=payload
            # )
            # await api_caller.close()

            # if openrouter_response.is_error:
            #     error_body = openrouter_response.json() if openrouter_response.content else {}
            #     error_message = (error_body.get("error") or {}).get("message") or openrouter_response.text
            #     logging.error(
            #         f"user={user_id} openrouter generation failed "
            #         f"task_uid={task_uid} status={openrouter_response.status_code} message={error_message}"
            #     )
            #     generation.status = GenerationStatuses.failed
            #     generation.status_code = openrouter_response.status_code
            #     generation.response = error_body
            #     await self.db.flush()
            #     raise ServiceError(status_code=openrouter_response.status_code, message=error_message)

            # logging.info(f"user={user_id} openrouter generation succeeded task_uid={task_uid}")
            # openrouter_body = openrouter_response.json()
            # images = openrouter_body.get("data") or []
            # usage = openrouter_body.get("usage") or {}

            # generation.status = GenerationStatuses.success
            # generation.status_code = 200
            # generation.response = openrouter_body
            # generation.token_usage = usage.get("total_tokens")
            # generation.cost = usage.get("cost")
            # await self.db.flush()

            # """Push each generated image to Udin and persist its result"""
            # upload = DfEngineGenerationUploads(generation_id=generation.id)
            # self.db.add(upload)
            # await self.db.flush()

            # udin_api_caller = APICaller()
            # any_failed = False
            # for idx, image in enumerate(images):
            #     udin_response = await udin_api_caller.udin(
            #         "POST",
            #         f"{UDIN_BASE_URL}/engine/storage/upload-generated-image/{task['project']['uid']}",
            #         user_id=user_id,
            #         raise_for_status=False,
            #         headers={"X-API-Key": UDIN_API_KEY},
            #         json={"b64_json": image.get("b64_json"), "media_type": image.get("media_type")},
            #     )
            #     if udin_response.is_error:
            #         any_failed = True
            #         logging.error(
            #             f"user={user_id} udin upload failed task_uid={task_uid} "
            #             f"generation_id={generation.id} status={udin_response.status_code}"
            #         )
            #         self.db.add(
            #             DfEngineGenerationReconciliationIssues(
            #                 generation_id=generation.id,
            #                 upload_id=upload.id,
            #                 issue_type="udin_upload_failed",
            #                 detail=udin_response.text,
            #             )
            #         )
            #         continue

            #     udin_data = udin_response.json()["data"]
            #     self.db.add(
            #         DfEngineGenerationResults(
            #             generation_id=generation.id,
            #             name=udin_data["name"],
            #             path=udin_data["path"],
            #             size=udin_data["size"],
            #             md5=udin_data.get("md5"),
            #             is_main=idx == 0,
            #             created_by=user_id,
            #         )
            #     )
            # await udin_api_caller.close()

            # upload.upload_status = UploadStatuses.failed if any_failed else UploadStatuses.success
            # upload.needs_reconciliation = any_failed
            # if not any_failed:
            #     upload.uploaded_at = local_time()
            # await self.db.flush()

            # response.data = user_generations

        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/user-galleries/{task_uid}",
        summary="List the user's generated image and video galleries.",
        description=(
            "Returns every image and video the current user has generated for this task, grouped "
            "into families: whichever version is currently marked as the main one is shown at the "
            "top, and its earlier variants are tucked underneath it. Each entry also says what the "
            "user is allowed to do with it right now, e.g. archive, favorite, or set as main. "
            "Cache-first, so repeat views load instantly."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_fetch_all_generation_galleries(
        self,
        task_uid: UUID = Path(description="Task UID"),
    ) -> Response:
        response = Response()
        file_service = FilesService()
        cache_key = CacheKeys()
        try:
            project_task = await file_service.get_project_task(self.db, task_uid)

            user_galleries_key = cache_key.user_galleries(self.user["user_id"], project_task["id"])
            cached = await get_json(self.redis, user_galleries_key)
            if cached is not None:
                logging.info(f"user={self.user['user_id']} listed user galleries source=cache task_uid={task_uid}")
                response.data = cached
                return response

            records = await query(
                db=self.db,
                table=DfEngineGenerations,
                options=(
                    selectinload(DfEngineGenerations.model_option),  # type: ignore
                    selectinload(DfEngineGenerations.result.and_(DfEngineGenerationResults.archieved_at.is_(None)))  # type: ignore
                    .selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                    selectinload(DfEngineGenerations.result.and_(DfEngineGenerationResults.archieved_at.is_(None)))  # type: ignore
                    .selectinload(DfEngineGenerationResults.updated_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                ),
                filters=(
                    DfEngineGenerations.created_by == self.user["user_id"],
                    DfEngineGenerations.task_id == project_task["id"],
                ),
            )
            records = [serialize(record) for record in records]
            for record in records:
                model = record.get("model_option", None)
                result = record.get("result", None)

                record["generation_uid"] = record.pop("uid", None)
                record["type"] = record.pop("kind", None)
                record["file_uid"] = result.get("uid") if result else None
                record["model"] = model.get("name") if model else None
                record["creator"] = format_user_employees(record.pop("created_by_user", None))
                record["created_at"] = format_datetime(record["created_at"])
                record["archieved_at"] = format_datetime(result.get("archieved_at")) if result else None
                record["cost"] = format_idr(record["cost"], USD_TO_IDR_RATE)

                record["file_id"] = result.get("id") if result else None
                record["parent_id"] = result.get("parent_id") if result else None
                record["md5"] = result.get("md5") if result else None
                record["name"] = result.get("name") if result else None
                record["path"] = format_udin_url(result.get("path")) if result else None
                record["size"] = format_size(result.get("size")) if result else None
                record["is_favourite"] = result.get("is_favourite") if result else None
                record["is_main"] = result.get("is_main") if result else None
                record["source"] = "generated"
                record["variants"] = []
                record["action"] = {
                    "can_fetch_detail": self.user["user_id"] == record["created_at"],
                    "can_generate_detail": record["is_main"] is True,
                    "can_set_main": record["is_main"] is False,
                    "can_archieve": record["archieved_at"] is None
                    and result is not None
                    and record["is_main"] is False,
                    "can_unarchieve": record["archieved_at"] is not None and result is not None,
                    "can_favorited": record["is_favourite"] is False,
                    "can_unfavorited": record["is_favourite"] is True,
                    "can_download": record["created_by"] == int(self.user["user_id"]),
                }

                record.pop("id", None)
                record.pop("model_option", None)
                record.pop("model_id", None)
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
                record.pop("result", None)
                record.pop("archieved_at", None)

            map_record_file_id = {record["file_id"]: record for record in records if record.get("file_id") is not None}

            map_childrens = {}
            for record in records:
                parent_id = record.get("parent_id")
                if parent_id is not None:
                    map_childrens.setdefault(parent_id, []).append(record)

            absorbed_file_ids = set()
            for record in records:
                if record.get("is_main") is not True:
                    continue

                file_id = record.get("file_id")
                family_root_id = record.get("parent_id") or file_id

                family = []
                root = map_record_file_id.get(family_root_id)
                if root is not None:
                    family.append(root)
                for child in map_childrens.get(family_root_id, []):
                    family.append(child)

                variants = []
                for member in family:
                    if member.get("file_id") != file_id:
                        member.pop("variants", None)
                        variants.append(member)
                        absorbed_file_ids.add(member["file_id"])
                record["variants"] = variants

            remaining_records = []
            for record in records:
                if record.get("file_id") not in absorbed_file_ids:
                    record["total_data"] = len(record["variants"])
                    remaining_records.append(record)
                record.pop("file_id", None)
                record.pop("parent_id", None)

            records = remaining_records
            await set_json(self.redis, user_galleries_key, records)
            logging.info(f"user={self.user['user_id']} listed user galleries source=db task_uid={task_uid}")
            response.data = records
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
