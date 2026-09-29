import traceback
from collections import defaultdict
from typing import Any, Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import delete, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.menu_management import MenuPayload
from services.dto import ConnectionContext
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.mysql import query
from apps.secret import OPENROUTER_API_KEY
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
    Employees,
    ProjectTasks,
    Users,
    DfEngineApiKeys,
    Projects,
)
from config.variables import USD_TO_IDR_RATE
from services.mysql.model.df_engine_generations import GENERATION_KIND_ICON_COLOR, GenerationKinds, GenerationStatuses
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.redis import get_json, set_json, delete_pattern, CacheKeys
from services.menu_management import MenuManagementService
from services.dto.asynced.projects import get_project, get_project_task
from services.dto.asynced.employees import get_employee
from services.dto.asynced.generation_files import (
    get_generation_main_files,
    get_upload_references,
    get_generation_references,
    get_generation_main_file_detail,
    get_generation_main_variants,
    get_generation_files,
)
from services.dto.asynced.uploaded_files import get_uploaded_files
from services.dto.asynced.api_keys import get_api_key, validate_api_key_limitation
from services.dto.asynced.admin_settings import get_admin_settings, get_project_setting, get_model, get_menu
from log import logging
from schemas.payload.generations import GenerationsPayload
from error import ServiceError, BaseError, DataNotFoundError, DataValidationError
from services.model_management import ModelManagement
from utils.serializer import serialize
from validations.prompt import rank_prompt
from validations.model import validate_image_parameter, validate_references
from parser.openrouter import parse_generation_payload
from services.api_caller import APICaller
from services.redis import CacheKeys
from apps.secret import OPENROUTER_BASE_URL, UDIN_API_KEY, UDIN_BASE_URL
from services.tasks.image_generation import image_generation
from services.dto.format_response import GenerationResultRecord
from utils.formatter import format_datetime, format_user_employees

cache_key = CacheKeys()


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
        search: Optional[str] = Query(
            None, min_length=1, description="Search by file name (starts with). Leave empty to include all files."
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project = await get_project(ctx, project_uid=project_uid)
            project_id = project["id"]

            upload_rows = await get_upload_references(ctx, user_id, project_id=project_id, search=search)
            generation_rows = await get_generation_references(ctx, user_id, project_id=project_id, search=search)

            buckets: dict[str, list[dict[str, Any]]] = {
                "Image Uploads": [],
                "Video Uploads": [],
                "Image Generations": [],
                "Video Generations": [],
                "Favorites": [],
                "Elements": [],
            }
            for row in upload_rows:
                label = "Image Uploads" if row["kind"] == UploadFileTypes.image else "Video Uploads"
                buckets[label].append(row["file"])

            generation_kind_labels = {
                GenerationKinds.image: "Image Generations",
                GenerationKinds.video: "Video Generations",
                GenerationKinds.element: "Elements",
            }
            for row in generation_rows:
                labels = [generation_kind_labels[row["kind"]]] if row["kind"] in generation_kind_labels else []
                if row["favourited"]:
                    labels.append("Favorites")
                for label in labels:
                    buckets[label].append(row["file"])

            response.data = [
                {"type": label, "total_data": len(files), "files": files} for label, files in buckets.items()
            ]
            section_counts = {section["type"]: section["total_data"] for section in response.data}
            logging.info(
                f"user={user_id} listed reference picker project_id={project_id} search={search} "
                f"uploads={len(upload_rows)} generations={len(generation_rows)} sections={section_counts}"
            )
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
        search: Optional[str] = Query(None, min_length=1),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            upload_rows = await get_upload_references(ctx, user_id, search=search)
            generation_rows = await get_generation_references(ctx, user_id, search=search)

            buckets = {
                "Image Uploads": defaultdict(lambda: {"tasks": defaultdict(list)}),
                "Video Uploads": defaultdict(lambda: {"tasks": defaultdict(list)}),
                "Image Generations": defaultdict(lambda: {"tasks": defaultdict(list)}),
                "Video Generations": defaultdict(lambda: {"tasks": defaultdict(list)}),
                "Favorites": defaultdict(lambda: {"tasks": defaultdict(list)}),
                "Elements": defaultdict(lambda: {"tasks": defaultdict(list)}),
            }
            for row in upload_rows:
                label = "Image Uploads" if row["kind"] == UploadFileTypes.image else "Video Uploads"
                project = buckets[label][row["project_id"]]
                project["id"] = row["project_id"]
                project["name"] = row["project_name"]
                project["tasks"][row["task_id"]].append(row["file"])

            generation_kind_labels = {
                GenerationKinds.image: "Image Generations",
                GenerationKinds.video: "Video Generations",
                GenerationKinds.element: "Elements",
            }
            for row in generation_rows:
                labels = [generation_kind_labels[row["kind"]]] if row["kind"] in generation_kind_labels else []
                if row["favourited"]:
                    labels.append("Favorites")
                for label in labels:
                    project = buckets[label][row["project_id"]]
                    project["id"] = row["project_id"]
                    project["name"] = row["project_name"]
                    project["tasks"][row["task_id"]].append(row["file"])

            response.data = [
                {
                    "type": label,
                    "total_data": sum(len(files) for p in bucket.values() for files in p["tasks"].values()),
                    "projects": [
                        {
                            "id": p["id"],
                            "name": p["name"],
                            "tasks": [{"id": tid, "files": files} for tid, files in p["tasks"].items()],
                        }
                        for p in bucket.values()
                    ],
                }
                for label, bucket in buckets.items()
            ]
            section_counts = {section["type"]: section["total_data"] for section in response.data}
            logging.info(
                f"user={user_id} listed global reference picker search={search} "
                f"uploads={len(upload_rows)} generations={len(generation_rows)} sections={section_counts}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/generations/enhance/{task_uid}",
        summary="Enhance prompt",
        description=(
            "Refines and expands the user's original prompt for the generation task "
            "identified by `task_uid`, adding clarity and detail to improve output quality. "
            "Returns the enhanced prompt without starting a new generation."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_enhance_user_prompt(
        self, task_uid: UUID = Path(..., description="Task UID.")
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
        "/generations/image-edit/{file_uid}",
        summary="Edit generated image",
        description=(
            "Applies the user's edit instructions to the previously generated image "
            "identified by `file_uid` and produces a new, modified version of it. "
            "The original image is preserved."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_edit_generated_image(
        self, file_uid: UUID = Path(description="File UID.")
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
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)

        # TASK_STATUS_ONPROCESS = 1
        # PROJECT_STATUS_ONGOING = 1

        try:
            task = await get_project_task(ctx, task_uid)
            # if task['status'] != TASK_STATUS_ONPROCESS:
            #     raise DataValidationError(message="project_task_not_onprocess")

            project = await get_project(ctx, project_id=task["project_id"])
            # if project['status'] != PROJECT_STATUS_ONGOING:
            #     raise DataValidationError(message="project_not_ongoing")

            employee_user = await get_employee(ctx, user_id=user_id)
            employee_boss = await get_employee(ctx, employee_id=employee_user["boss_id"])

            admin_setting = await get_admin_settings(ctx)
            project_setting = await get_project_setting(ctx, project_uid=project["uid"])
            if len(schema.prompt) > project_setting["compose_input_max_chars"]:
                raise DataValidationError(
                    message="prompt_length_exceeded",
                    context={"length": len(schema.prompt), "max_chars": project_setting["compose_input_max_chars"]},
                )

            menu = await get_menu(ctx, user_id, menu_uid=schema.menu_uid, feature_uid=schema.feature_uid)
            matched_feature = next(feature for feature in menu["features"] if feature["uid"] == str(schema.feature_uid))  # type: ignore
            injected_prompts = [template["prompt"] for template in matched_feature["prompt_templates"]]
            merged_prompt = "\n".join([schema.prompt, *injected_prompts])

            assistant_setting = admin_setting.get("assistant_model")
            enhancer_setting = admin_setting.get("enhancer_model")
            generation_model = await get_model(
                ctx, schema.model_uid, ModelUsageTypes.image if schema.type == "image" else ModelUsageTypes.video
            )
            assistant_model = (
                await get_model(ctx, assistant_setting["uid"], ModelUsageTypes.text) if assistant_setting else None
            )
            enhancer_model = (
                await get_model(ctx, enhancer_setting["uid"], ModelUsageTypes.text) if enhancer_setting else None
            )
            ranking_model = enhancer_model or assistant_model
            if ranking_model is None:
                raise DataValidationError(message="ranking_model_not_configured")

            generated_file_uids = [str(ref.file_uid) for ref in schema.references if ref.type == "generated"]
            uploaded_file_uids = [str(ref.file_uid) for ref in schema.references if ref.type == "upload"]

            uploaded_files = await get_uploaded_files(ctx, uploaded_file_uids)
            generated_files = await get_generation_files(ctx, file_uids=generated_file_uids)

            diva_references = [str(ref.diva_url) for ref in schema.references if ref.type == "diva"]
            uploaded_file_references = [record["path"] for record in uploaded_files]
            generated_references = [record["path"] for record in generated_files]
            all_references = await validate_references(
                [*diva_references, *uploaded_file_references, *generated_references],
                generation_model["supported_parameters"],
            )

            api_key = await get_api_key(
                ctx, 3
            )  # Later will be filled with employee_boss["id"], currently we override using static value
            await validate_api_key_limitation(ctx, project["id"], api_key["id"])
            await rank_prompt(
                schema.prompt,
                ranking_model["model_id"],
                api_key["key"],
                GenerationKinds.image if schema.type == "image" else GenerationKinds.video,
            )

            """Insert generation record"""
            generation = DfEngineGenerations(
                kind=schema.type,  # type: ignore
                model_id=generation_model["id"],
                menu_id=menu["id"],  # type: ignore
                feature_id=matched_feature["id"],
                sourceable_id=api_key["id"],
                sourceable_type=DfEngineApiKeys.__name__,
                project_id=project["id"],
                task_id=task["id"],
                prompt=schema.prompt,
                full_prompt=merged_prompt,
                parameter=schema.parameter,
                created_by=user_id,
            )
            self.db.add(generation)
            await self.db.flush()

            """Insert reference records using data already fetched via get_uploaded_files/get_generation_files"""
            for file in uploaded_files:
                self.db.add(DfEngineUploadFileReferences(generation_id=generation.id, file_id=file["id"]))
            for file in generated_files:
                self.db.add(DfEngineGenerationReferences(generation_id=generation.id, result_id=file["id"]))
            await self.db.flush()

            match schema.type:
                case "image":
                    validate_image_parameter(schema.parameter, generation_model["supported_parameters"])
                    payload = parse_generation_payload(
                        schema.type,
                        generation_model["model_id"],
                        merged_prompt,
                        schema.parameter,
                        all_references,
                    )
                    self.db.add(DfEngineImageGenerationDetails(generation_id=generation.id, parameter=payload))
                    await self.db.commit()
                    image_generation.delay(  # type:ignore
                        generation.id,
                        user_id,
                        headers={
                            "Authorization": f"Bearer {OPENROUTER_API_KEY}"
                        },  # Later will be changed from API key from boss_id
                        payload=payload,
                    )
                case _:
                    """Will be configured later"""
                    await self.db.commit()
                    return response

            """Invalidate cache related to is_main listings, same as set-main"""
            await delete_pattern(self.redis, cache_key.generation_files_main_list_pattern(task["id"]))
            await delete_pattern(self.redis, cache_key.generation_files_references_picker_pattern(user_id))
            await delete_pattern(ctx.redis, ctx.key.user_galleries_pattern(user_id))
            await delete_pattern(ctx.redis, ctx.key.generation_file_detail_pattern(user_id))
            await self.redis.delete(cache_key.generation_files_result_list(user_id, project["id"]))

            generation_detail_key = cache_key.generation_detail(user_id, str(generation.uid))
            cached_generation_detail = await get_json(ctx.redis, generation_detail_key)
            if cached_generation_detail is not None:
                response.data = cached_generation_detail
                return response

            record = serialize(
                await query(
                    db=self.db,
                    table=DfEngineGenerations,
                    options=(
                        selectinload(DfEngineGenerations.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineGenerations.model_option).load_only(DfEngineModelOptions.name),  # type: ignore
                    ),
                    filters=(DfEngineGenerations.id == generation.id,),
                    fetch_one=True,
                )
            )
            response.data = GenerationResultRecord(
                kind=record["kind"],
                generation_uid=record["uid"],
                created_at=format_datetime(record["created_at"]),
                icon=GENERATION_KIND_ICON_COLOR.get(record["kind"], {}).get("icon"),
                color=GENERATION_KIND_ICON_COLOR.get(record["kind"], {}).get("color"),
                status=record["status"],
                creator=format_user_employees(record.get("created_by_user")),
                model=(record.get("model_option") or {}).get("name"),
                prompt=record["prompt"],
                parameter=record.get("parameter"),
            ).model_dump(
                mode="json",
                exclude={
                    "flag_created_at",
                    "flag_favourited_at",
                    "flag_archieved_at",
                    "version",
                    "updated_at",
                    "full_prompt",
                    "parameter",
                },
            )
            response.data["type"] = record["kind"]
            await set_json(ctx.redis, generation_detail_key, response.data)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/generations/{file_uid}",
        summary="Fetch a generated file's result.",
        description="Poll this once a generation finishes (e.g. after a Pusher success event) to fetch the final generated file record.",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_file_uid_to_fetch_result(
        self, file_uid: UUID = Path(description="Generated file UID.")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            generation_file_detail_key = cache_key.generation_file_detail(user_id, str(file_uid))
            cached_generation_file_detail = await get_json(ctx.redis, generation_file_detail_key)
            if cached_generation_file_detail is not None:
                response.data = cached_generation_file_detail
                return response

            record = serialize(
                await query(
                    db=self.db,
                    table=DfEngineGenerationResults,
                    options=(
                        selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineGenerationResults.generation)  # type: ignore
                        .load_only(
                            DfEngineGenerations.uid,  # type: ignore
                            DfEngineGenerations.kind,  # type: ignore
                            DfEngineGenerations.status,  # type: ignore
                            DfEngineGenerations.prompt,  # type: ignore
                            DfEngineGenerations.full_prompt,  # type: ignore
                            DfEngineGenerations.cost,  # type: ignore
                        )
                        .selectinload(DfEngineGenerations.model_option)  # type: ignore
                        .load_only(DfEngineModelOptions.name),  # type: ignore
                    ),
                    filters=(DfEngineGenerationResults.uid == str(file_uid),),  # type: ignore
                    fetch_one=True,
                )
            )
            if not record:
                raise DataNotFoundError(message="generation_file_not_found")

            response.data = GenerationResultRecord.from_result(record, user_id).model_dump(
                mode="json",
                exclude={
                    "flag_created_at",
                    "flag_favourited_at",
                    "flag_archieved_at",
                    "is_main",
                    "version",
                    "updated_at",
                    "full_prompt",
                },
            )
            await set_json(ctx.redis, generation_file_detail_key, response.data)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/user-galleries/{task_uid}",
        summary="List generation galleries for a task",
        description=(
            "Returns the current (main) file version of every image or video generated on this task; "
            "older versions are grouped underneath the current one rather than listed separately. "
            "Set `my_task=true` to only see files you generated yourself, or leave it false to also "
            "include the current version generated by other members. Use `search` to filter by "
            "prompt, model name, or file name (prefix match)."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_uid_to_fetch_all_generation_galleries(
        self,
        task_uid: UUID = Path(description="Task UID"),
        my_task: bool = Query(
            False,
            description=(
                "If true, only return the current (main) file version you personally generated. "
                "If false, also include the current version generated by other members on this task."
            ),
        ),
        search: Optional[str] = Query(
            None,
            min_length=1,
            description=(
                "Prefix search across the generation prompt, model name, and file name. "
                "Leave empty to return all files."
            ),
        ),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        owner_id = user_id if my_task else None
        try:
            task = await get_project_task(ctx, task_uid)
            response.data = await get_generation_main_files(ctx, user_id, task["id"], owner_id, search)
            logging.info(
                f"user={user_id} fetched user galleries task_uid={task_uid} owner_id={owner_id} "
                f"search={search} count={len(response.data)}"
            )
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
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            variants = await get_generation_main_variants(ctx, file_uid, user_id)
            target = next((variant for variant in variants if variant["file_uid"] == str(file_uid)), None)
            if not target:
                raise DataNotFoundError(message="main_generation_file_not_found")

            if target["is_main"]:
                response.data = await get_generation_main_file_detail(ctx, file_uid, user_id)
            else:
                generation_variant_key = cache_key.generation_files_variant_detail(file_uid)
                generation_variant_cached = await get_json(ctx.redis, generation_variant_key)
                if generation_variant_cached is not None:
                    response.data = generation_variant_cached
                else:
                    await set_json(ctx.redis, generation_variant_key, target)
                    response.data = target
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
