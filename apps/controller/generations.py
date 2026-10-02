import traceback
from collections import defaultdict
from typing import Any, Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import PromptEnhancerResult, Response
from services.dto import ConnectionContext
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.mysql import query
from services.mysql.model import (
    DfEngineModelOptions,
    DfEngineGenerations,
    DfEngineGenerationReferences,
    DfEngineGenerationResults,
    DfEngineUploadFileReferences,
    DfEngineUploadFiles,
    Employees,
    Users,
    DfEngineApiKeys,
)
from services.mysql.model.df_engine_generations import GENERATION_KIND_ICON_COLOR, GenerationKinds, GenerationStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.redis import get_json, set_json, delete_pattern, CacheKeys
from services.dto.asynced.projects import get_project, get_project_task
from services.dto.asynced.employees import get_employee
from services.dto.asynced.generation_files import (
    get_generation_main_files,
    get_upload_references,
    get_generation_references,
    get_generation_main_file_detail,
    get_generation_main_variants,
    get_generation_files,
    get_enhance_prompt,
)
from services.dto.asynced.generation_files import _build_references
from services.dto.asynced.uploaded_files import get_uploaded_files
from services.dto.asynced.api_keys import get_api_key, validate_api_key_limitation
from services.dto.asynced.admin_settings import get_admin_settings, get_project_setting, get_model, get_menu
from log import logging
from schemas.payload.generations import ImageVideoGenerationPayload, PromptEnhancerPayload, EditImageGenerationPayload
from error import ServiceError, BaseError, DataNotFoundError, DataValidationError
from services.model_management import ModelManagement
from utils.serializer import serialize
from validations.prompt import enhance_prompt, rank_prompt
from validations.model import (
    validate_image_model_parameter,
    validate_video_model_parameter,
    validate_total_image_references,
    validate_image_availability,
)
from parser.openrouter import parse_openrouter_payload
from services.redis import CacheKeys
from services.tasks.image_generation import image_generation
from services.tasks.video_generation import video_generation
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
        self, schema: PromptEnhancerPayload, task_uid: UUID = Path(..., description="Task UID.")
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

            enhancer_setting = admin_setting.get("enhancer_model")
            enhancer_model = (
                await get_model(ctx, enhancer_setting["uid"], ModelUsageTypes.text) if enhancer_setting else None
            )

            if enhancer_model is None:
                raise DataValidationError(message="enhancer_model_not_configured")

            api_key = await get_api_key(ctx, employee_boss["id"])
            await validate_api_key_limitation(ctx, project["id"], api_key["id"])
            enhanced = await enhance_prompt(merged_prompt, enhancer_model["model_id"], api_key["key"], user_id)

            generation = DfEngineGenerations(
                kind=GenerationKinds.enhancer,
                model_id=enhancer_model["id"],
                menu_id=menu["id"],  # type: ignore
                feature_id=matched_feature["id"],
                sourceable_id=api_key["id"],
                sourceable_type=DfEngineApiKeys.__name__,
                project_id=project["id"],
                task_id=task["id"],
                prompt=schema.prompt,
                full_prompt=merged_prompt,
                response=enhanced["text"],
                status=GenerationStatuses.success,
                status_code=enhanced["status_code"],
                token_usage=enhanced["usage"].get("total_tokens"),
                cost=enhanced["usage"].get("cost"),
                created_by=user_id,
            )
            self.db.add(generation)
            await self.db.flush()

            response.data = PromptEnhancerResult(prompt=enhanced["text"], enhance_uid=generation.uid)  # type: ignore
            await set_json(
                ctx.redis,
                cache_key.enhancer_detail(str(generation.uid)),
                {
                    "id": generation.id,
                    "prompt": generation.prompt,
                    "full_prompt": generation.full_prompt,
                    "response": enhanced["text"],
                    "enhance_uid": str(generation.uid),
                },
            )
            logging.info(f"user={user_id} enhanced prompt task_uid={task_uid} enhance_uid={generation.uid}")
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
        self, schema: EditImageGenerationPayload, file_uid: UUID = Path(description="File UID.")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)

        TASK_STATUS_ONPROCESS = 1
        PROJECT_STATUS_ONGOING = 1

        try:
            generated_files = await get_generation_files(ctx, user_id=user_id, file_uids=[str(file_uid)])
            source_file = generated_files[0]
            edit_parent_id = source_file["parent_id"] or source_file["id"]
            task_id = serialize(
                await query(
                    db=self.db,
                    columns=(DfEngineGenerations.task_id,),
                    table=DfEngineGenerations,
                    filters=(DfEngineGenerations.uid == generated_files[0]["generation_uid"],),
                    fetch_one=True,
                )
            )

            task = await get_project_task(ctx, task_id=task_id)
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

            resolved_prompt = schema.prompt
            enhance_id = None
            if schema.enhance_uid:
                enhanced = await get_enhance_prompt(ctx, schema.enhance_uid)
                response.data = enhanced
                enhance_id = enhanced["id"]
                resolved_prompt = enhanced["response"]

            menu = await get_menu(ctx, user_id, menu_uid=schema.menu_uid, feature_uid=schema.feature_uid)
            matched_feature = next(feature for feature in menu["features"] if feature["uid"] == str(schema.feature_uid))  # type: ignore
            injected_prompts = [template["prompt"] for template in matched_feature["prompt_templates"]]
            merged_prompt = "\n".join([resolved_prompt, *injected_prompts])
            if schema.x_min is not None:
                merged_prompt = "\n".join(
                    [
                        merged_prompt,
                        f"Apply edits only within the focus area (normalized 0-1 coordinates): "
                        f"x_min={schema.x_min}, x_max={schema.x_max}, y_min={schema.y_min}, y_max={schema.y_max}.",
                    ]
                )

            assistant_setting = admin_setting.get("assistant_model")
            enhancer_setting = admin_setting.get("enhancer_model")
            generation_model = await get_model(ctx, schema.model_uid, ModelUsageTypes.image)
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
            generated_file_uids.append(str(file_uid))
            uploaded_file_uids = [str(ref.file_uid) for ref in schema.references if ref.type == "upload"]

            uploaded_files = await get_uploaded_files(ctx, uploaded_file_uids)
            generated_files = await get_generation_files(ctx, file_uids=generated_file_uids)

            diva_references = [str(ref.diva_url) for ref in schema.references if ref.type == "diva"]
            uploaded_file_references = [record["path"] for record in uploaded_files]
            generated_references = [record["path"] for record in generated_files]
            user_image_references = [*diva_references, *uploaded_file_references, *generated_references]

            input_references_parameter = (generation_model["supported_parameters"] or {}).get(
                "input_references", {"max": 0}
            )
            validate_total_image_references(user_image_references, input_references_parameter)
            all_references = await validate_image_availability(user_image_references)

            api_key = await get_api_key(ctx, employee_boss["id"])
            await validate_api_key_limitation(ctx, project["id"], api_key["id"])
            await rank_prompt(
                resolved_prompt,
                ranking_model["model_id"],
                api_key["key"],
                GenerationKinds.image,
            )

            """Insert generation record"""
            generation = DfEngineGenerations(
                kind=GenerationKinds.image_edit,
                model_id=generation_model["id"],
                menu_id=menu["id"],  # type: ignore
                feature_id=matched_feature["id"],
                sourceable_id=api_key["id"],
                sourceable_type=DfEngineApiKeys.__name__,
                project_id=project["id"],
                task_id=task["id"],
                prompt=resolved_prompt,
                full_prompt=merged_prompt,
                parameter=schema.parameter,
                created_by=user_id,
                enhance_id=enhance_id,
            )
            self.db.add(generation)
            await self.db.flush()

            """Insert reference records using data already fetched via get_uploaded_files/get_generation_files"""
            for file in uploaded_files:
                self.db.add(DfEngineUploadFileReferences(generation_id=generation.id, file_id=file["id"]))
            for file in generated_files:
                self.db.add(DfEngineGenerationReferences(generation_id=generation.id, result_id=file["id"]))
            await self.db.flush()

            validate_image_model_parameter(schema.parameter, generation_model)
            if schema.parameter.get("n", 1) != 1:
                raise DataValidationError(
                    message="generation_parameters_invalid", error={"n": ["generation_parameter_above_maximum"]}
                )
            payload = parse_openrouter_payload(
                generation_model["model_id"],
                merged_prompt,
                schema.parameter,
                all_references,
                "image",
            )
            await self.db.commit()  # must be visible to the Celery worker's own DB connection before dispatch
            image_generation.delay(  # type:ignore
                generation.id,
                user_id,
                headers={"Authorization": f"Bearer {api_key['key']}"},
                payload=payload,
            )

            """Invalidate cache related to is_main listings, same as set-main"""
            await delete_pattern(self.redis, cache_key.generation_files_main_list_pattern(task["id"]))
            await delete_pattern(self.redis, cache_key.generation_files_references_picker_pattern(user_id))
            await delete_pattern(ctx.redis, ctx.key.user_galleries_pattern(user_id))
            await delete_pattern(ctx.redis, ctx.key.generation_file_detail_pattern(user_id))
            await self.redis.delete(cache_key.generation_files_result_list(user_id, project["id"]))

            generation_detail_key = cache_key.generation_detail(user_id, str(generation.uid))
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
                parent_id=edit_parent_id,
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
                    "parameter",
                },
            )
            response.data["type"] = record["kind"]
            await set_json(ctx.redis, generation_detail_key, response.data)
            logging.info(
                f"user={user_id} queued image edit file_uid={file_uid} generation_uid={generation.uid} "
                f"parent_id={edit_parent_id}"
            )
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
        self, schema: ImageVideoGenerationPayload, task_uid: UUID = Path(description="Task UID")
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

            resolved_prompt = schema.prompt
            enhance_id = None
            if schema.enhance_uid:
                enhanced = await get_enhance_prompt(ctx, schema.enhance_uid)
                response.data = enhanced
                enhance_id = enhanced["id"]
                resolved_prompt = enhanced["response"]

            menu = await get_menu(ctx, user_id, menu_uid=schema.menu_uid, feature_uid=schema.feature_uid)
            matched_feature = next(feature for feature in menu["features"] if feature["uid"] == str(schema.feature_uid))  # type: ignore
            injected_prompts = [template["prompt"] for template in matched_feature["prompt_templates"]]
            merged_prompt = "\n".join([resolved_prompt, *injected_prompts])

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

            """Image References"""
            generated_file_uids = [str(ref.file_uid) for ref in schema.references if ref.type == "generated"]
            uploaded_file_uids = [str(ref.file_uid) for ref in schema.references if ref.type == "upload"]

            uploaded_files = await get_uploaded_files(ctx, uploaded_file_uids)
            generated_files = await get_generation_files(ctx, file_uids=generated_file_uids)

            diva_references = [str(ref.diva_url) for ref in schema.references if ref.type == "diva"]
            uploaded_file_references = [record["path"] for record in uploaded_files]
            generated_references = [record["path"] for record in generated_files]

            user_image_references = [*diva_references, *uploaded_file_references, *generated_references]
            input_references_parameter = (
                (generation_model["supported_parameters"] or {}).get("input_references", {"max": 0})
                if schema.type == "image"
                else None
            )

            validate_total_image_references(user_image_references, input_references_parameter)
            validated_image_references = await validate_image_availability(user_image_references)

            api_key = await get_api_key(ctx, employee_boss["id"])
            await validate_api_key_limitation(ctx, project["id"], api_key["id"])

            await rank_prompt(
                resolved_prompt,
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
                prompt=resolved_prompt,
                full_prompt=merged_prompt,
                parameter=schema.parameter,
                created_by=user_id,
                enhance_id=enhance_id,
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
                    validate_image_model_parameter(schema.parameter, generation_model)
                    payload = parse_openrouter_payload(
                        generation_model["model_id"],
                        merged_prompt,
                        schema.parameter,
                        validated_image_references,
                        schema.type,
                    )

                    await self.db.commit()
                    image_generation.delay(  # type:ignore
                        generation.id,
                        user_id,
                        headers={"Authorization": f"Bearer {api_key['key']}"},
                        payload=payload,
                    )
                case _:
                    """Video frame references"""
                    frame_image_generated_uids = [
                        str(ref.file_uid) for ref in schema.frame_images if ref.type == "generated"
                    ]
                    frame_image_uploaded_uids = [
                        str(ref.file_uid) for ref in schema.frame_images if ref.type == "upload"
                    ]

                    frame_image_uploaded_files = await get_uploaded_files(ctx, frame_image_uploaded_uids)
                    frame_image_generated_files = await get_generation_files(ctx, file_uids=frame_image_generated_uids)

                    uploaded_path_by_uid = {record["file_uid"]: record["path"] for record in frame_image_uploaded_files}
                    generated_path_by_uid = {
                        record["file_uid"]: record["path"] for record in frame_image_generated_files
                    }

                    unvalidated_frame_images = [
                        {
                            "frame_type": ref.frame_type,
                            "image": (
                                str(ref.diva_url)
                                if ref.type == "diva"
                                else uploaded_path_by_uid[str(ref.file_uid)]
                                if ref.type == "upload"
                                else generated_path_by_uid[str(ref.file_uid)]
                            ),
                        }
                        for ref in schema.frame_images
                    ]

                    validated_frame_image_paths = await validate_image_availability(
                        [frame["image"] for frame in unvalidated_frame_images]
                    )
                    validated_frame_images = [
                        {"frame_type": frame["frame_type"], "image": image}
                        for frame, image in zip(unvalidated_frame_images, validated_frame_image_paths)
                    ]

                    validate_video_model_parameter(
                        {**schema.parameter, "frame_images": validated_frame_images}, generation_model
                    )
                    payload = parse_openrouter_payload(
                        generation_model["model_id"],
                        merged_prompt,
                        schema.parameter,
                        validated_image_references,
                        schema.type,
                        validated_frame_images,
                    )

                    await self.db.commit()
                    video_generation.delay(  # type:ignore
                        generation.id,
                        user_id,
                        headers={"Authorization": f"Bearer {api_key['key']}"},
                        payload=payload,
                    )

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
                    "parameter",
                },
            )
            response.data["type"] = record["kind"]
            await set_json(ctx.redis, generation_detail_key, response.data)
            logging.info(
                f"user={user_id} queued {schema.type} generation task_uid={task_uid} generation_uid={generation.uid}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/generation-main-results/{generation_uid}",
        summary="Fetch generation main result.",
        description="Poll this once a generation finishes (e.g. after a Pusher success event) to fetch the final generated file record.",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_generation_uid_to_fetch_main_generation_result(
        self, generation_uid: UUID = Path(description="Generation UID.")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            record = serialize(
                await query(
                    ctx.db,
                    DfEngineGenerationResults,
                    joins=(DfEngineGenerationResults.generation,),  # type: ignore
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
                    filters=(
                        DfEngineGenerations.uid == str(generation_uid),  # type: ignore
                        DfEngineGenerationResults.is_main == True,  # type: ignore
                        DfEngineGenerations.kind.in_(  # type: ignore
                            ["image", "image_edit", "video"],
                        ),
                    ),
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
            logging.info(f"user={user_id} fetched generation result source=db generation_uid={generation_uid}")
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/generation-edit-results/{generation_uid}",
        summary="Fetch image edit generation result.",
        description="Returns the full record for a specific generated file version, including action flags and references.",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_with_generation_uid_to_fetch_edit_result(
        self, generation_uid: UUID = Path(description="Generation UID.")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            generation_id = (
                select(DfEngineGenerations.id)  # type: ignore
                .where(
                    DfEngineGenerations.uid == str(generation_uid),
                    DfEngineGenerations.kind.in_(  # type: ignore
                        ["image", "image_edit", "video"],
                    ),
                )
                .scalar_subquery()
            )
            record = serialize(
                await query(
                    ctx.db,
                    DfEngineGenerationResults,
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
                        selectinload(DfEngineGenerationResults.generation)  # type: ignore
                        .selectinload(DfEngineGenerations.generation_references)  # type: ignore
                        .selectinload(DfEngineGenerationReferences.result)  # type: ignore
                        .selectinload(DfEngineGenerationResults.generation)  # type: ignore
                        .selectinload(DfEngineGenerations.model_option),  # type: ignore
                        selectinload(DfEngineGenerationResults.generation)  # type: ignore
                        .selectinload(DfEngineGenerations.generation_references)  # type: ignore
                        .selectinload(DfEngineGenerationReferences.result)  # type: ignore
                        .selectinload(DfEngineGenerationResults.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineGenerationResults.generation)  # type: ignore
                        .selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
                        .selectinload(DfEngineUploadFileReferences.file),  # type: ignore
                        selectinload(DfEngineGenerationResults.generation)  # type: ignore
                        .selectinload(DfEngineGenerations.upload_file_references)  # type: ignore
                        .selectinload(DfEngineUploadFileReferences.file)  # type: ignore
                        .selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                    ),
                    filters=(DfEngineGenerationResults.generation_id == generation_id,),  # type: ignore
                    fetch_one=True,
                )
            )
            if not record:
                raise DataNotFoundError(message="generation_file_not_found")
            response.data = {
                **GenerationResultRecord.from_result(record, user_id).model_dump(
                    mode="json",
                    exclude={"flag_created_at", "flag_favourited_at", "flag_archieved_at"},
                ),
                "references": _build_references(record.get("generation") or {}),
            }
            logging.info(f"user={user_id} fetched edit result detail generation_uid={generation_uid}")
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
            logging.info(
                f"user={user_id} fetched generated file details file_uid={file_uid} is_main={target['is_main']}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
