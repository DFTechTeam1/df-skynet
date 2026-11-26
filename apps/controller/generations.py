import asyncio
import json
import re
import traceback
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID
from fastapi import status, Path, Query, Depends, Request
from fastapi import Response as FastAPIResponse
from fastapi_controller import controller
from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload, load_only
from apps.controller.core import CoreDependencies
from schemas.response import PaginationResponse, PromptEnhancerResult, Response
from schemas.format.reference_pickers import GeneratedFile, ReferencePicker, UploadedFile
from services.dto import ConnectionContext
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.mysql import get_usd_rate, query
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
    DfEngineChatAssistants,
    DfEngineGuardrailValidations,
    Projects,
    EntertainmentTaskSongs,
    ProjectTasks,
    ProjectSongLists,
    SONG_STATUS_ON_PROGRESS,
    SONG_STATUS_COMPLETED,
    TASK_STATUS_ONGOING,
    TASK_STATUS_COMPLETED,
    DfEngineProjectSettings,
    DfEngineSettings,
    DfEngineChatSessions,
    ProjectPersonInCharges,
    TransferTeamMembers,
    DfEngineMenus,
    DfEngineMenuFeatureMappings,
    DfEngineFeatures,
    DfEngineFeaturePromptMappings,
    DfEnginePromptTemplates,
    DfEnginePromptTemplateReferences,
)
from services.mysql.model.projects import PROJECT_STATUS_ONGOING
from services.mysql.model.transfer_team_members import TRANSFER_STATUS_APPROVED
from services.mysql.model.df_engine_generations import GENERATION_KIND_ICON_COLOR, GenerationKinds, GenerationStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.redis import get_json, set_json, delete_pattern, invalidate_project_files, CacheKeys
from sqlalchemy.exc import IntegrityError
from services.dto.asynced.projects import get_project, get_project_task
from services.dto.asynced.employees import EMPLOYEE_STATUS_RESIGNED, get_employee, assigned_to_task
from services.dto.asynced.files import get_user_uploaded_files_refactored
from services.dto.asynced.generation_files import (
    get_generation_main_files,
    get_upload_references,
    get_generation_references,
    get_generation_main_file_detail,
    get_generation_main_variants,
    get_generation_files,
    get_enhance_prompt,
    get_generation_main_refactored,
)
from services.dto.asynced.generation_files import _build_references, _enhancer, overlay_favourites, overlay_prompts
from services.dto.asynced.uploaded_files import get_uploaded_files
from services.dto.asynced.api_keys import get_employee_api_key, validate_api_key_limitation
from services.dto.asynced.admin_settings import (
    PROJECT_SETTING_LIMIT_FIELDS,
    SETTING_CODE,
    get_admin_settings,
    get_project_setting,
    get_model,
    get_menu,
)
from log import logging
from schemas.payload.generations import ImageVideoGenerationPayload, PromptEnhancerPayload, EditImageGenerationPayload
from services.files import has_override
from error import (
    AuthorizationError,
    ServiceError,
    BaseError,
    RateLimitedError,
    DataNotFoundError,
    DataValidationError,
)
from services.generations import dispatch_generation, global_reference_sections, reference_sections, validation_record
from services.search.query import search_project_files, search_task_generations
from utils import local_time
from utils.serializer import serialize
from validations.prompt import enhance_prompt, validate_prompt
from schemas.format.openrouter import Message, PromptGuardrailResponse
from middlewares.lang import current_lang, resolve_message
from services.openrouter import GUARDRAIL_INSTRUCTION, call_prompt_guardrail
from validations.model import (
    validate_image_generation_parameter,
    validate_image_model_parameter,
    validate_video_model_parameter,
    validate_total_image_references,
    validate_image_availability,
)
from parser.openrouter import parse_openrouter_payload
from services import frame_reference_color
from services.redis import CacheKeys
from services.tasks.image_generation import image_generation
from services.tasks.video_generation import video_generation
from services.dto.format_response import GenerationResultRecord, prompt_fields
from utils.formatter import format_datetime, format_udin_url, format_user_employees
from apps.dependency.rate_limitter import generation_throttle

cache_key = CacheKeys()
IMAGE_GUARDRAIL_TYPES = ("prompt_injection", "nfsw", "image_generation")
IMAGE_KINDS = (GenerationKinds.image, GenerationKinds.image_edit)  # an upload's "image" type matches too


class GenerationsController(CoreDependencies):
    @controller.get(
        "/references-picker/{project_uid}",
        summary="Get reference pickers",
        description=(
            "Shows your uploaded and generated files for one project, sorted into image uploads, image generations, "
            "and elements, so you can pick one to reuse. You can search by file name."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
    )
    async def generation_to_fetch_references_picker(
        self,
        project_uid: UUID = Path(..., description="Project UID."),
        search: Optional[str] = Query(
            None,
            min_length=1,
            description="Search by file name, file path, task name. Leave empty to include all files.",
        ),
        my_task: bool = Query(False, description="Filtered only creator files"),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        is_overrider = self.user["is_overrider"]
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        try:
            project_id = await self.project_repo.get_project(
                columns=(Projects.id,),
                filters=(Projects.uid == str(project_uid),),
            )

            if search:
                uploaded_docs, generated_docs = await search_project_files(
                    str(project_uid),
                    search,
                    ("image", "image_edit"),
                    user_id,
                    is_overrider,
                    my_task,
                )
                await overlay_favourites(ctx, generated_docs, user_id)
                generated_files = [GeneratedFile(**doc) for doc in generated_docs]
                uploaded_files = [UploadedFile(**doc) for doc in uploaded_docs if doc["kind"] == "image"]
            else:
                generations = await self.generation_result_repo.get_picker_files(project_id, user_id, my_task)
                uploads = await self.uploaded_file_repo.get_picker_files(project_id, user_id, my_task)
                generated_files = [GeneratedFile.from_result(file, user_id, is_overrider) for file in generations]
                uploaded_files = [UploadedFile.from_result(file, user_id, is_overrider) for file in uploads]

            response.data = [
                ReferencePicker(type="Image Generations", files=generated_files),
                ReferencePicker(type="Image Uploads", files=uploaded_files),
                ReferencePicker(type="Elements", files=[]),
            ]
            logging.info(
                f"user={user_id} listed reference picker project_id={project_id} my_task={my_task} search={search}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(
                f"user={user_id} failed to list reference picker project_uid={project_uid} my_task={my_task}\n"
                f"{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.post(
        "/generations/image-edit/{file_uid}",
        summary="Image edit",
        description=(
            "Applies the user's edit instructions to the previously generated image "
            "identified by `file_uid` and produces a new, modified version of it. "
            "The original image is preserved."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
        dependencies=[Depends(generation_throttle)],
    )
    async def generation_with_uid_to_edit_generated_image(
        self, schema: EditImageGenerationPayload, file_uid: UUID = Path(description="File UID.")
    ) -> Response:
        """Edit an image: validate the request, then queue a job that creates the new version.

        The source is an uploaded file or an earlier generation, chosen by `schema.source`. Every free check
        runs before the prompt guardrail, which is the first paid call. A Celery task creates the image later.
        If the guardrail refuses the prompt or fails, the request stops there with an error and no generation.

        Raises:
            AuthorizationError: The user may not edit this file.
            DataNotFoundError: A required record doesn't exist.
            DataValidationError: A project, request, limit or guardrail rule isn't met.
            ServiceError: The guardrail provider failed, or something unexpected happened.
        """
        response = Response()
        user_id = int(self.user["user_id"])
        prompt_guardrails = None
        global_project_settings = None
        assistant_model = None
        queued_generation_uid = None  # set once the job is queued, so a later failure is easy to spot in the logs
        log_prefix = f"[image-edit] user={user_id} file_uid={file_uid} source={schema.source}"
        try:
            logging.info(
                f"{log_prefix} started model_uid={schema.model_uid} menu_uid={schema.menu_uid} "
                f"feature_uid={schema.feature_uid} references={len(schema.references)} prompt_chars={len(schema.prompt)}"
            )

            # Get the source file with its project, task and song. Only its creator or an overrider may edit it.
            if schema.source == "upload":
                target_file = await self.uploaded_file_repo.get_uploaded_file(
                    columns=(DfEngineUploadFiles,),
                    options=(
                        load_only(
                            DfEngineUploadFiles.type,  # type: ignore
                            DfEngineUploadFiles.created_by,  # type: ignore
                            DfEngineUploadFiles.project_id,  # type: ignore
                            DfEngineUploadFiles.task_id,  # type: ignore
                            DfEngineUploadFiles.song_id,  # type: ignore
                            DfEngineUploadFiles.path,  # type: ignore
                        ),
                        selectinload(DfEngineUploadFiles.project).options(  # type: ignore
                            load_only(Projects.status, Projects.project_class_id),  # type: ignore
                            selectinload(Projects.project_person_in_charges)  # type: ignore
                            .load_only(ProjectPersonInCharges.pic_id, ProjectPersonInCharges.is_lead)  # type: ignore
                            .selectinload(ProjectPersonInCharges.pic)  # type: ignore
                            .load_only(Employees.nickname)  # type: ignore
                            .selectinload(
                                Employees.api_keys.and_(
                                    DfEngineApiKeys.is_main.is_(True), DfEngineApiKeys.hash.isnot(None)
                                )  # type: ignore
                            )
                            .load_only(DfEngineApiKeys.employee_id, DfEngineApiKeys.key, DfEngineApiKeys.expires_at),  # type: ignore
                            selectinload(
                                Projects.transfer_team_members.and_(
                                    TransferTeamMembers.status == TRANSFER_STATUS_APPROVED
                                )  # type: ignore
                            ).load_only(TransferTeamMembers.employee_id, TransferTeamMembers.requested_by),  # type: ignore
                            selectinload(Projects.project_setting).load_only(  # type: ignore
                                *(getattr(DfEngineProjectSettings, field) for field in PROJECT_SETTING_LIMIT_FIELDS)
                            ),
                        ),
                        selectinload(DfEngineUploadFiles.task).load_only(ProjectTasks.status),  # type: ignore
                        selectinload(DfEngineUploadFiles.song)  # type: ignore
                        .load_only(ProjectSongLists.id)  # type: ignore
                        .selectinload(ProjectSongLists.entertainment_task_songs)  # type: ignore
                        .load_only(EntertainmentTaskSongs.status),  # type: ignore
                    ),
                    filters=(DfEngineUploadFiles.uid == str(file_uid),),
                )
                if not self.user["is_overrider"] and target_file["created_by"] != user_id:
                    raise AuthorizationError(message="uploaded_file_edit_not_permitted")
                target_file["kind"] = target_file.pop("type")
                target_file["parent_id"] = None
            else:
                target_file = await self.generation_result_repo.get_generation_file(
                    columns=(DfEngineGenerationResults,),
                    options=(
                        load_only(
                            DfEngineGenerationResults.created_by,  # type: ignore
                            DfEngineGenerationResults.generation_id,  # type: ignore
                            DfEngineGenerationResults.parent_id,  # type: ignore
                            DfEngineGenerationResults.path,  # type: ignore
                        ),
                        selectinload(DfEngineGenerationResults.generation).options(  # type: ignore
                            load_only(
                                DfEngineGenerations.kind,  # type: ignore
                                DfEngineGenerations.project_id,  # type: ignore
                                DfEngineGenerations.task_id,  # type: ignore
                                DfEngineGenerations.song_id,  # type: ignore
                            ),
                            selectinload(DfEngineGenerations.project).options(  # type: ignore
                                load_only(Projects.status, Projects.project_class_id),  # type: ignore
                                selectinload(Projects.project_person_in_charges)  # type: ignore
                                .load_only(ProjectPersonInCharges.pic_id, ProjectPersonInCharges.is_lead)  # type: ignore
                                .selectinload(ProjectPersonInCharges.pic)  # type: ignore
                                .load_only(Employees.nickname)  # type: ignore
                                .selectinload(
                                    Employees.api_keys.and_(
                                        DfEngineApiKeys.is_main.is_(True), DfEngineApiKeys.hash.isnot(None)
                                    )  # type: ignore
                                )
                                .load_only(
                                    DfEngineApiKeys.employee_id, DfEngineApiKeys.key, DfEngineApiKeys.expires_at
                                ),  # type: ignore
                                selectinload(
                                    Projects.transfer_team_members.and_(
                                        TransferTeamMembers.status == TRANSFER_STATUS_APPROVED
                                    )  # type: ignore
                                ).load_only(TransferTeamMembers.employee_id, TransferTeamMembers.requested_by),  # type: ignore
                                selectinload(Projects.project_setting).load_only(  # type: ignore
                                    *(getattr(DfEngineProjectSettings, field) for field in PROJECT_SETTING_LIMIT_FIELDS)
                                ),
                            ),
                            selectinload(DfEngineGenerations.task).load_only(ProjectTasks.status),  # type: ignore
                            selectinload(DfEngineGenerations.song)  # type: ignore
                            .load_only(ProjectSongLists.id)  # type: ignore
                            .selectinload(ProjectSongLists.entertainment_task_songs)  # type: ignore
                            .load_only(EntertainmentTaskSongs.status),  # type: ignore
                        ),
                    ),
                    filters=(DfEngineGenerationResults.uid == str(file_uid),),
                )
                if not self.user["is_overrider"] and target_file["created_by"] != user_id:
                    raise AuthorizationError(message="generated_file_edit_not_permitted")

                target_file = {**target_file.pop("generation"), **target_file}

                # Versions are grouped under the original, so editing a child keeps the child's parent
                target_file["parent_id"] = target_file["parent_id"] or target_file["id"]

            # Flatten the related records so both sources have the same shape
            project = target_file.pop("project") or {}
            task = target_file.pop("task") or {}
            song_assignments = (target_file.pop("song") or {}).get("entertainment_task_songs") or []
            target_file["project_status"] = project.get("status")
            target_file["task_status"] = task.get("status")
            target_file["song_status"] = song_assignments[0]["status"] if song_assignments else None
            target_file.pop("generation_id", None)

            logging.info(
                f"{log_prefix} source loaded project_id={target_file['project_id']} task_id={target_file['task_id']} "
                f"song_id={target_file['song_id']} kind={target_file['kind']}"
            )

            # Only images can be edited
            if target_file["kind"] not in IMAGE_KINDS:
                raise DataValidationError(message="file_edit_image_only")

            # The project must be ongoing
            if target_file["project_status"] != PROJECT_STATUS_ONGOING:
                raise DataValidationError(message="project_not_ongoing")

            # The project needs exactly one lead, who has exactly one main API key
            if not project["project_person_in_charges"]:
                raise DataValidationError(message="project_pic_not_assigned")

            project_leads = [pic for pic in project["project_person_in_charges"] if pic["is_lead"]]
            if not project_leads:
                raise DataValidationError(message="project_lead_not_assigned")

            if len(project_leads) > 1:
                raise DataValidationError(message="project_lead_multiple", context={"total_lead": len(project_leads)})

            lead_pic = project_leads[0]["pic"]
            if not lead_pic["api_keys"]:
                raise DataValidationError(
                    message="project_lead_api_key_not_found", context={"nickname": lead_pic["nickname"]}
                )

            if len(lead_pic["api_keys"]) > 1:
                raise DataValidationError(
                    message="project_lead_api_key_multiple",
                    context={"nickname": lead_pic["nickname"], "total_key": len(lead_pic["api_keys"])},
                )

            lead_employee_id = project_leads[0]["pic_id"]

            # The source must belong to a task or a song, and that task or song must be ongoing
            if target_file["task_id"] is None and target_file["song_id"] is None:
                if schema.source == "upload":
                    raise DataValidationError(message="file_edit_task_required")
                raise DataNotFoundError(message="project_task_not_found")

            if target_file["task_id"] is not None:
                if target_file["task_status"] == TASK_STATUS_COMPLETED:
                    raise DataValidationError(message="project_task_already_completed")

                if target_file["task_status"] != TASK_STATUS_ONGOING:
                    raise DataValidationError(message="project_task_not_ongoing")

            if target_file["song_id"] is not None:
                if target_file["song_status"] == SONG_STATUS_COMPLETED:
                    raise DataValidationError(message="song_task_already_completed")

                if target_file["song_status"] != SONG_STATUS_ON_PROGRESS:
                    raise DataValidationError(message="song_task_not_ongoing")

            logging.info(f"{log_prefix} project and task checks passed lead_employee_id={lead_employee_id}")

            # Get the assistant model, guardrail rules and per-class limits
            admin_settings = await self.admin_repo.get_setting(
                filters=(
                    DfEngineSettings.code == SETTING_CODE,  # type: ignore
                    DfEngineSettings.key.in_(["assistant_model", "prompt_guardrails", "project_class_limitations"]),  # type: ignore
                ),
                fetch_one=False,
                raise_if_null=False,
            )

            for setting in admin_settings:
                if setting["key"] == "assistant_model":
                    assistant_model = setting["value"]
                if setting["key"] == "prompt_guardrails":
                    prompt_guardrails = setting["value"]
                if setting["key"] == "project_class_limitations":
                    global_project_settings = setting["value"]

            # Use the project's own limits, otherwise the limits of its project class
            limits = project["project_setting"]
            if not limits:
                if project["project_class_id"] is None:
                    raise DataValidationError(message="project_class_not_assigned")
                if not global_project_settings:
                    raise DataValidationError(message="global_project_setting_not_configured")
                limits = next(
                    (item for item in global_project_settings if item.get("id") == project["project_class_id"]), None
                )
                if not limits:
                    raise DataNotFoundError(message="project_class_limitation_not_found")

            limit_source = "project_setting" if project["project_setting"] else f"class_{project['project_class_id']}"
            logging.info(f"{log_prefix} limits resolved source={limit_source}")
            project_settings = {field: limits.get(field) for field in PROJECT_SETTING_LIMIT_FIELDS}

            # Get the current user's employee record. Resigned employees are blocked.
            get_user = await self.user_repo.get_user(
                filters=(Users.id == user_id,),
                columns=(Users,),
                options=(
                    load_only(Users.id),  # type: ignore
                    selectinload(Users.employees).load_only(Employees.boss_id, Employees.status),  # type: ignore
                ),
            )

            if not get_user["employees"]:
                raise DataValidationError(message="employee_not_found")

            if get_user["employees"]["status"] == EMPLOYEE_STATUS_RESIGNED:
                raise DataValidationError(message="employee_resigned")

            employee_id = get_user["employees"]["id"]
            boss_id = get_user["employees"]["boss_id"]

            # The prompt must fit the project limit
            if len(schema.prompt) > project_settings["compose_input_max_chars"]:
                raise DataValidationError(
                    message="prompt_length_exceeded",
                    context={"length": len(schema.prompt), "max_chars": project_settings["compose_input_max_chars"]},
                )

            # Get the menu with only the requested feature and its active prompt templates.
            # An empty mapping list means the feature isn't under this menu.
            menu = await self.menu_repo.get_menu(
                columns=(DfEngineMenus,),
                filters=(DfEngineMenus.uid == str(schema.menu_uid),),
                options=(
                    load_only(DfEngineMenus.id),  # type: ignore
                    selectinload(
                        DfEngineMenus.df_engine_menu_feature_mappings.and_(  # type: ignore
                            DfEngineMenuFeatureMappings.df_engine_features.has(  # type: ignore
                                DfEngineFeatures.uid == str(schema.feature_uid)
                            )
                        )
                    )
                    .load_only(DfEngineMenuFeatureMappings.feature_id)  # type: ignore
                    .selectinload(DfEngineMenuFeatureMappings.df_engine_features)  # type: ignore
                    .load_only(DfEngineFeatures.is_active)  # type: ignore
                    .selectinload(DfEngineFeatures.df_engine_feature_prompt_mappings)  # type: ignore
                    .selectinload(
                        DfEngineFeaturePromptMappings.df_engine_prompt_templates.and_(  # type: ignore
                            DfEnginePromptTemplates.is_active.is_(True)  # type: ignore
                        )
                    )
                    .selectinload(DfEnginePromptTemplates.template_references)  # type: ignore
                    .selectinload(
                        DfEnginePromptTemplateReferences.reference.and_(  # type: ignore
                            DfEnginePromptTemplates.is_active.is_(True)  # type: ignore
                        )
                    ),
                ),
            )
            if not menu["df_engine_menu_feature_mappings"]:
                raise DataValidationError(message="feature_not_under_menu")

            feature = menu["df_engine_menu_feature_mappings"][0]["df_engine_features"]
            if not feature["is_active"]:
                raise DataValidationError(message="feature_inactive")

            # Collect the feature's prompts: each template, then the templates it references, without duplicates
            prompts_by_uid: dict[str, str] = {}
            for mapping in sorted(feature["df_engine_feature_prompt_mappings"], key=lambda item: item["id"]):
                template = mapping["df_engine_prompt_templates"]
                if not template:  # inactive templates are filtered out by the query
                    continue
                referenced = [item["reference"] for item in template["template_references"]]
                for entry in (template, *referenced):
                    if entry:
                        prompts_by_uid.setdefault(entry["uid"], entry["prompt"])
            injected_prompts = list(prompts_by_uid.values())

            # Get the selected image model, which must be usable
            generation_model = await self.model_option_repo.get_model(
                columns=(
                    DfEngineModelOptions.id,
                    DfEngineModelOptions.model_id,
                    DfEngineModelOptions.supported_parameters,
                ),
                filters=(
                    DfEngineModelOptions.uid == str(schema.model_uid),
                    DfEngineModelOptions.type == ModelUsageTypes.image,
                    DfEngineModelOptions.is_enabled.is_(True),  # type: ignore
                    DfEngineModelOptions.is_available.is_(True),  # type: ignore
                    DfEngineModelOptions.deleted_at.is_(None),  # type: ignore
                    func.json_length(DfEngineModelOptions.supported_parameters) >= 1,
                ),
            )

            logging.info(
                f"{log_prefix} menu, feature and model valid model_id={generation_model['id']} "
                f"feature_prompts={len(injected_prompts)}"
            )

            # Check the parameters against the model. Image edit creates one image, whatever the model allows.
            if schema.parameter.get("n", 1) != 1:
                raise DataValidationError(message="image_single_output")

            validate_image_generation_parameter(schema.parameter, generation_model["supported_parameters"])

            # Check the image count against the model's limit. The edited file is also sent to the model,
            # so it counts once, even when it's listed as a reference too.
            extra_references = [
                ref for ref in schema.references if not (ref.type == schema.source and ref.file_uid == file_uid)
            ]
            total_references = 1 + len(extra_references)
            input_references = generation_model["supported_parameters"].get("input_references") or {"max": 0}
            if total_references > input_references["max"]:
                raise DataValidationError(
                    message="input_references_limit",
                    context={"total": total_references, "max": input_references["max"]},
                )

            # Get the referenced files from the database. DiVA references are URLs, so there's nothing to look up.
            reference_uploads = []
            reference_results = []
            upload_uids = [str(ref.file_uid) for ref in extra_references if ref.type == "upload"]
            if upload_uids:
                reference_uploads = await self.uploaded_file_repo.get_uploaded_file(
                    columns=(
                        DfEngineUploadFiles.id,
                        DfEngineUploadFiles.uid,
                        DfEngineUploadFiles.type.label("kind"),  # type: ignore
                        DfEngineUploadFiles.path,
                    ),
                    filters=(DfEngineUploadFiles.uid.in_(upload_uids),),  # type: ignore
                    fetch_one=False,
                    raise_if_null=False,
                )
            generated_uids = [str(ref.file_uid) for ref in extra_references if ref.type == "generated"]
            if generated_uids:
                reference_results = await self.generation_result_repo.get_generation_file(
                    columns=(
                        DfEngineGenerationResults.id,
                        DfEngineGenerationResults.uid,
                        DfEngineGenerationResults.path,
                        DfEngineGenerations.kind,
                    ),
                    joins=(DfEngineGenerationResults.generation,),
                    filters=(DfEngineGenerationResults.uid.in_(generated_uids),),  # type: ignore
                    fetch_one=False,
                    raise_if_null=False,
                )

            # Every referenced file must exist and be an image. Report all bad ones by list index.
            reference_rows = {
                "upload": {item["uid"]: item for item in reference_uploads},
                "generated": {item["uid"]: item for item in reference_results},
            }
            reference_errors = {}
            for ref in extra_references:
                if ref.type == "diva":
                    continue
                row = reference_rows[ref.type].get(str(ref.file_uid))
                if row is None:
                    reference_errors[f"references.{ref.position}"] = [f"reference_{ref.type}_not_found"]
                elif row["kind"] not in IMAGE_KINDS:
                    reference_errors[f"references.{ref.position}"] = [f"reference_{ref.type}_not_image"]
            if reference_errors:
                raise DataValidationError(message="reference_check_failed", error=reference_errors)

            logging.info(f"{log_prefix} parameters and references valid input_images={total_references}")

            # Pick the API key to charge: the user's own, then the transfer requester's,
            # then the boss's, and finally the project lead's
            pic_api_keys = {
                pic["pic_id"]: pic["pic"]["api_keys"][0]
                for pic in project["project_person_in_charges"]
                if pic["pic"]["api_keys"]
            }

            key_source = "own"
            project_api_key = pic_api_keys.get(employee_id)

            if not project_api_key:
                requested_by_map = {
                    member["employee_id"]: member["requested_by"] for member in project["transfer_team_members"]
                }
                if employee_id in requested_by_map:
                    project_api_key = pic_api_keys.get(requested_by_map[employee_id])
                    key_source = f"transfer_requester_{requested_by_map[employee_id]}"

            if not project_api_key and boss_id:
                project_api_key = pic_api_keys.get(boss_id)
                key_source = f"boss_{boss_id}"

            if not project_api_key:
                project_api_key = lead_pic["api_keys"][0]
                key_source = f"lead_{lead_employee_id}"

            # Reject an expired key, because using another one would charge a different person
            expires_at = project_api_key["expires_at"]
            if expires_at and datetime.fromisoformat(expires_at) <= local_time():
                key_owner = next(
                    pic["pic"]["nickname"]
                    for pic in project["project_person_in_charges"]
                    if pic["pic_id"] == project_api_key["employee_id"]
                )
                raise DataValidationError(message="selected_api_key_expired", context={"nickname": key_owner})

            logging.info(
                f"{log_prefix} api key resolved api_key_id={project_api_key['id']} employee_id={employee_id} "
                f"key_source={key_source} key_owner={project_api_key['employee_id']}"
            )

            # Get the project's cost limit. No threshold means the full limit.
            threshold = project_settings["token_limit_threshold"]
            cost_limit = project_settings["token_usage_limit"] * (1.0 if threshold is None else threshold)

            # Add up what the project spent on chats, generations and the guardrail checks of both
            chat_spent = await self.chat_assistant_repo.get_chat_assistant(
                columns=(func.coalesce(func.sum(DfEngineChatAssistants.cost), 0),),
                joins=((DfEngineChatSessions, DfEngineChatSessions.id == DfEngineChatAssistants.session_id),),
                filters=(DfEngineChatSessions.project_id == target_file["project_id"],),
            )
            generation_spent = await self.generation_repo.get_generation(
                columns=(func.coalesce(func.sum(DfEngineGenerations.cost), 0),),
                filters=(DfEngineGenerations.project_id == target_file["project_id"],),
            )
            guardrail_spent = await self.guardrail_validation_repo.get_guardrail_validation(
                columns=(func.coalesce(func.sum(DfEngineGuardrailValidations.cost), 0),),
                joins=(
                    (
                        DfEngineChatAssistants,
                        and_(
                            DfEngineChatAssistants.id == DfEngineGuardrailValidations.sourceable_id,  # type: ignore
                            DfEngineGuardrailValidations.sourceable_type == DfEngineChatAssistants.__name__,  # type: ignore
                        ),
                    ),
                    (DfEngineChatSessions, DfEngineChatSessions.id == DfEngineChatAssistants.session_id),
                ),
                filters=(DfEngineChatSessions.project_id == target_file["project_id"],),
            )
            generation_guardrail_spent = await self.guardrail_validation_repo.get_guardrail_validation(
                columns=(func.coalesce(func.sum(DfEngineGuardrailValidations.cost), 0),),
                joins=(
                    (
                        DfEngineGenerations,
                        and_(
                            DfEngineGenerations.id == DfEngineGuardrailValidations.sourceable_id,  # type: ignore
                            DfEngineGuardrailValidations.sourceable_type == DfEngineGenerations.__name__,  # type: ignore
                        ),
                    ),
                ),
                filters=(DfEngineGenerations.project_id == target_file["project_id"],),
            )
            refused_guardrail_spent = await self.guardrail_validation_repo.get_guardrail_validation(
                columns=(func.coalesce(func.sum(DfEngineGuardrailValidations.cost), 0),),
                filters=(
                    DfEngineGuardrailValidations.sourceable_type == Projects.__name__,  # type: ignore
                    DfEngineGuardrailValidations.sourceable_id == target_file["project_id"],  # type: ignore
                ),
            )
            guardrail_spent += generation_guardrail_spent + refused_guardrail_spent

            total_spent = chat_spent + generation_spent + guardrail_spent
            logging.info(
                f"{log_prefix} cost check chat={chat_spent} generation={generation_spent} guardrail={guardrail_spent} "
                f"total={total_spent} limit={cost_limit}"
            )
            if total_spent > cost_limit:
                raise DataValidationError(
                    message="project_cost_limit_exceeded",
                    context={"action": "image edit", "spent": f"${total_spent:.2f}", "limit": f"${cost_limit:.2f}"},
                )

            # Check the prompt against the active guardrail rules for image generation
            validation_fields = None  # the guardrail call to record, when one was made
            prompt_validations = [rule for rule in prompt_guardrails or [] if rule["type"] in IMAGE_GUARDRAIL_TYPES]
            if not prompt_validations:
                logging.info(f"{log_prefix} guardrail skipped, no active image rules")
            else:
                if not assistant_model or not {"id", "model_id"} <= set(assistant_model):
                    raise DataValidationError(message="default_model_not_configured", context={"model": "assistant"})

                guardrail_messages = [
                    Message.build("system", text).to_payload()
                    for text in (GUARDRAIL_INSTRUCTION.strip(), *(rule["instruction"] for rule in prompt_validations))
                ]
                guardrail_messages.append(Message.build("user", schema.prompt).to_payload())

                logging.info(
                    f"{log_prefix} guardrail calling model_id={assistant_model['id']} "
                    f"rules={[rule['type'] for rule in prompt_validations]}"
                )

                # Ask the assistant model to classify the prompt
                rejection = None
                validation_fields = {"payload": {}, "response": {}, "total_tokens": 0, "cached_tokens": 0, "cost": 0}
                try:
                    guardrail = await call_prompt_guardrail(
                        api_key=project_api_key["key"],
                        messages=guardrail_messages,
                        model=assistant_model["model_id"],
                        user_id=user_id,
                    )
                except ServiceError as exc:
                    # Recorded like chat does. The original `error` holds a bare status number,
                    # which the error handler can't render, so a clean error is raised instead.
                    rejection = ServiceError(status_code=exc.status_code, message=exc.message)
                    error_context = exc.context or {}
                    validation_fields.update(
                        payload=error_context.get("payload") or {},
                        response={"error": exc.error, "upstream_body": error_context.get("upstream_body")},
                        status_code=(exc.error or {}).get("upstream_status", exc.status_code),
                    )
                else:
                    body, verdict = {}, None
                    try:
                        body = guardrail.json()
                        verdict = PromptGuardrailResponse.model_validate_json(
                            body["choices"][0]["message"]["content"], strict=True
                        ).model_dump()
                    except Exception as exc:
                        # Log only the error type, because the traceback could repeat the model's reply
                        logging.error(
                            f"{log_prefix} guardrail reply unreadable status={guardrail.status_code} "
                            f"error={type(exc).__name__}"
                        )

                    usage = body.get("usage") or {}
                    validation_fields.update(
                        payload=json.loads(guardrail.request.content),
                        response=body,
                        status_code=guardrail.status_code,
                        total_tokens=usage.get("total_tokens") or 0,
                        cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                        cost=usage.get("cost") or 0,
                    )

                    if verdict is None:
                        rejection = DataValidationError(message="prompt_ranking_failed")
                    else:
                        # Only the rules that were sent can reject the prompt
                        flags = {rule["type"]: verdict[rule["type"]] for rule in prompt_validations}
                        if flags.get("prompt_injection"):
                            rejection = DataValidationError(message="prompt_injection_detected")
                        elif flags.get("nfsw"):
                            rejection = DataValidationError(message="prompt_nsfw_detected")
                        elif not flags.get("image_generation", True):
                            rejection = DataValidationError(message="prompt_not_image_related")

                logging.info(
                    f"{log_prefix} guardrail finished passed={rejection is None} "
                    f"status={validation_fields['status_code']} tokens={validation_fields['total_tokens']} "
                    f"cost={validation_fields['cost']}"
                )

                validation_fields.update(
                    apikeyable_id=project_api_key["id"],
                    apikeyable_type=DfEngineApiKeys.__name__,
                    model_id=assistant_model["id"],
                    message="Success",
                    exchange_rate=await self.db.run_sync(get_usd_rate),
                    created_by=user_id,
                )

                if rejection:
                    # Stop here without creating a generation. The paid call is still recorded, linked to the
                    # project because there's no generation, so it counts toward the cost limit
                    validation_fields["message"] = resolve_message(rejection.message, current_lang.get())
                    self.db.add(
                        DfEngineGuardrailValidations(
                            sourceable_id=target_file["project_id"],
                            sourceable_type=Projects.__name__,
                            **validation_fields,
                        )
                    )
                    await self.db.commit()
                    raise rejection

            # Build the image URLs for the model: the source first, then the references in order
            image_urls = [format_udin_url(target_file["path"])]
            upload_reference_ids, generated_reference_ids = [], []
            for ref in extra_references:
                if ref.type == "diva":
                    image_urls.append(str(ref.diva_url))
                    continue
                row = reference_rows[ref.type][str(ref.file_uid)]
                image_urls.append(format_udin_url(row["path"]))
                (upload_reference_ids if ref.type == "upload" else generated_reference_ids).append(row["id"])

            # Combine the user's prompt, the feature prompts and the focus area
            full_prompt = "\n".join([schema.prompt, *injected_prompts])
            if schema.x_min is not None:
                full_prompt = "\n".join(
                    [
                        full_prompt,
                        f"Apply edits only within the focus area (normalized 0-1 coordinates): "
                        f"x_min={schema.x_min}, x_max={schema.x_max}, y_min={schema.y_min}, y_max={schema.y_max}.",
                    ]
                )

            # Save the new generation
            project_id = target_file["project_id"]
            task_id = target_file["task_id"]
            song_id = target_file["song_id"] if task_id is None else None
            generation = DfEngineGenerations(
                kind=GenerationKinds.image if schema.source == "upload" else GenerationKinds.image_edit,
                model_id=generation_model["id"],
                menu_id=menu["id"],
                feature_id=menu["df_engine_menu_feature_mappings"][0]["feature_id"],
                sourceable_id=project_api_key["id"],
                sourceable_type=DfEngineApiKeys.__name__,
                project_id=project_id,
                task_id=task_id,
                song_id=song_id,
                raw_prompt=schema.prompt,
                full_prompt=full_prompt,
                finalized_prompt=full_prompt,
                parameter=schema.parameter,
                created_by=user_id,
            )
            self.db.add(generation)
            try:
                await self.db.flush()
            except IntegrityError:
                raise DataNotFoundError(message="project_task_not_found")

            # Save the source reference first. udin_uploader treats the lowest-id generation reference of an
            # image_edit as its source, and files the new version under that image's original.
            if schema.source == "upload":
                self.db.add(DfEngineUploadFileReferences(generation_id=generation.id, file_id=target_file["id"]))
            else:
                self.db.add(DfEngineGenerationReferences(generation_id=generation.id, result_id=target_file["id"]))
            await self.db.flush()
            self.db.add_all(
                [
                    DfEngineUploadFileReferences(generation_id=generation.id, file_id=file_id)
                    for file_id in upload_reference_ids
                ]
                + [
                    DfEngineGenerationReferences(generation_id=generation.id, result_id=result_id)
                    for result_id in generated_reference_ids
                ]
            )

            # Record the passed guardrail call, linked to its generation (that's how it reaches the project)
            if validation_fields:
                self.db.add(
                    DfEngineGuardrailValidations(
                        sourceable_id=generation.id,
                        sourceable_type=DfEngineGenerations.__name__,
                        **validation_fields,
                    )
                )

            logging.info(
                f"{log_prefix} generation prepared generation_id={generation.id} generation_uid={generation.uid} "
                f"upload_references={len(upload_reference_ids)} generated_references={len(generated_reference_ids)}"
            )

            # Commit before queueing, because the Celery worker uses its own database connection
            payload = parse_openrouter_payload(
                generation_model["model_id"], full_prompt, schema.parameter, image_urls, "image"
            )
            await self.db.commit()
            await dispatch_generation(
                self.db,
                generation,
                image_generation,
                user_id,
                headers={"Authorization": f"Bearer {project_api_key['key']}"},
                payload=payload,
            )
            queued_generation_uid = str(generation.uid)
            logging.info(f"{log_prefix} job queued generation_uid={queued_generation_uid}")

            # Clear the cached file lists that must now show the new generation
            await delete_pattern(self.redis, cache_key.generation_files_main_list_pattern(task_id or song_id))
            await invalidate_project_files(self.redis, cache_key, project_id)
            await delete_pattern(self.redis, cache_key.generation_file_detail_pattern(user_id))
            for pattern in cache_key.generation_files_user_lists_patterns(user_id):
                await delete_pattern(self.redis, pattern)

            # Build the response from the saved record, and cache it for the Celery task to update
            record = await self.generation_repo.get_generation(
                columns=(DfEngineGenerations,),
                filters=(DfEngineGenerations.id == generation.id,),
                options=(
                    selectinload(DfEngineGenerations.created_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                    selectinload(DfEngineGenerations.model_option).load_only(DfEngineModelOptions.name),  # type: ignore
                ),
            )
            response.data = GenerationResultRecord(
                kind=record["kind"],
                generation_uid=record["uid"],
                parent_id=target_file["parent_id"],
                created_at=format_datetime(record["created_at"]),
                icon=GENERATION_KIND_ICON_COLOR.get(record["kind"], {}).get("icon"),
                color=GENERATION_KIND_ICON_COLOR.get(record["kind"], {}).get("color"),
                status=record["status"],
                creator=format_user_employees(record.get("created_by_user")),
                model=(record.get("model_option") or {}).get("name"),
                **prompt_fields(record),
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
            await set_json(self.redis, cache_key.generation_detail(user_id, str(record["uid"])), response.data)
            logging.info(
                f"{log_prefix} completed generation_uid={queued_generation_uid} parent_id={target_file['parent_id']}"
            )
        except BaseError as e:
            log = logging.error if e.status_code >= 500 else logging.warning
            log(f"{log_prefix} rejected status={e.status_code} reason={e.message} context={e.context} error={e.error}")
            raise
        except Exception:
            logging.error(
                f"{log_prefix} failed queued_generation_uid={queued_generation_uid} "
                f"(if set, the job is already queued)\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.post(
        "/generations/{task_uid}",
        summary="Generate an image or video.",
        description="Creates a new image or video from your prompt using AI.",
        status_code=status.HTTP_200_OK,
        tags=["Generations"],
        response_model=Response,
        dependencies=[Depends(generation_throttle)],
    )
    async def generation_with_uid_to_generate_an_image_or_video(
        self, schema: ImageVideoGenerationPayload, task_uid: UUID = Path(description="Task UID")
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        can_override = has_override(self.user["roles"])

        try:
            task = await get_project_task(ctx, task_uid)
            project = await get_project(ctx, project_id=task["project_id"])
            if project["status"] != PROJECT_STATUS_ONGOING:
                raise DataValidationError(message="project_not_ongoing")

            if task.get("is_song") and task["status"] == SONG_STATUS_COMPLETED:
                raise DataValidationError(message="song_task_already_completed")
            if not task.get("is_song") and task["status"] == TASK_STATUS_COMPLETED:
                raise DataValidationError(message="project_task_already_completed")
            if task["status"] != (SONG_STATUS_ON_PROGRESS if task["is_song"] else TASK_STATUS_ONGOING):
                raise DataValidationError(
                    message="song_task_not_ongoing" if task["is_song"] else "project_task_not_ongoing"
                )

            employee_user = await get_employee(ctx, user_id=user_id)

            task_id = task["id"] if task["is_song"] is False else None
            song_id = task["id"] if task["is_song"] is True else None

            if can_override is False:
                """
                Ensure the user is assigned to this task, unless the accessed user has override roles.
                """
                await assigned_to_task(ctx, employee_user["id"], task_id, song_id)

            admin_setting = await get_admin_settings(ctx)
            project_setting = await get_project_setting(ctx, project_uid=project["uid"])

            if len(schema.prompt) > project_setting["compose_input_max_chars"]:
                raise DataValidationError(
                    message="prompt_length_exceeded",
                    context={"length": len(schema.prompt), "max_chars": project_setting["compose_input_max_chars"]},
                )

            enhance_id = None
            enhanced_prompt = None
            if schema.enhance_uid:
                enhanced = await get_enhance_prompt(ctx, schema.enhance_uid)
                response.data = enhanced
                enhance_id = enhanced["id"]
                enhanced_prompt = enhanced["response"]

            menu = await get_menu(ctx, user_id, menu_uid=schema.menu_uid, feature_uid=schema.feature_uid)
            matched_feature = next(feature for feature in menu["features"] if feature["uid"] == str(schema.feature_uid))  # type: ignore
            injected_prompts = [template["prompt"] for template in matched_feature["prompt_templates"]]
            full_prompt = "\n".join([schema.prompt, *injected_prompts])

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

            api_key = await get_employee_api_key(ctx, project["id"], employee_user)
            await validate_api_key_limitation(ctx, project["id"], api_key["id"])

            validated_image_references, _, final = await asyncio.gather(
                validate_image_availability(user_image_references),
                validate_prompt(
                    ctx,
                    schema.prompt,
                    ranking_model["model_id"],
                    api_key["key"],
                    user_id,
                    "image_generation" if schema.type == "image" else "video_generation",
                    record=validation_record(ranking_model["id"], api_key["id"], project["id"], task),
                ),
                asyncio.sleep(0, {"text": enhanced_prompt})
                if schema.enhance_uid
                else asyncio.sleep(0, {"text": full_prompt}),
                # else enhance_prompt(full_prompt, ranking_model["model_id"], api_key["key"], user_id),
            )
            finalized_prompt = final["text"]

            """Insert generation record"""
            generation = DfEngineGenerations(
                kind=schema.type,  # type: ignore
                model_id=generation_model["id"],
                menu_id=menu["id"],  # type: ignore
                feature_id=matched_feature["id"],
                sourceable_id=api_key["id"],
                sourceable_type=DfEngineApiKeys.__name__,
                project_id=project["id"],
                task_id=None if task.get("is_song") else task["id"],
                song_id=task["id"] if task.get("is_song") else None,
                raw_prompt=schema.prompt,
                full_prompt=full_prompt,
                finalized_prompt=finalized_prompt,
                parameter=schema.parameter,
                created_by=user_id,
                enhance_id=enhance_id,
                color_code=schema.default_frame_reference_color,  # type: ignore
            )
            self.db.add(generation)
            try:
                await self.db.flush()
            except IntegrityError:
                raise DataNotFoundError(message="project_task_not_found")

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
                        finalized_prompt,
                        schema.parameter,
                        validated_image_references,
                        schema.type,
                    )

                    await self.db.commit()
                    await dispatch_generation(
                        self.db,
                        generation,
                        image_generation,
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

                    color_frame_type = validate_video_model_parameter(
                        {**schema.parameter, "frame_images": validated_frame_images},
                        generation_model,
                        color=schema.default_frame_reference_color,  # type: ignore
                    )
                    payload = parse_openrouter_payload(
                        model_id=generation_model["model_id"],
                        prompt=finalized_prompt,
                        parameter=schema.parameter,
                        references=validated_image_references,
                        type=schema.type,
                        frame_images=validated_frame_images,
                    )
                    if color_frame_type:
                        color_url = await asyncio.to_thread(
                            frame_reference_color.create,
                            schema.default_frame_reference_color,  # type: ignore
                            schema.parameter["aspect_ratio"],
                        )
                        payload["frame_images"] = sorted(
                            [
                                *payload.get("frame_images", []),
                                {"frame_type": color_frame_type, "type": "image_url", "image_url": {"url": color_url}},
                            ],
                            key=lambda f: f["frame_type"] != "first_frame",
                        )

                    await self.db.commit()
                    await dispatch_generation(
                        self.db,
                        generation,
                        video_generation,
                        user_id,
                        headers={"Authorization": f"Bearer {api_key['key']}"},
                        payload=payload,
                    )

            """Invalidate cache related to is_main listings, same as set-main"""
            await delete_pattern(self.redis, cache_key.generation_files_main_list_pattern(task["id"]))
            await invalidate_project_files(self.redis, cache_key, project["id"])
            await delete_pattern(ctx.redis, ctx.key.generation_file_detail_pattern(user_id))
            for pattern in cache_key.generation_files_user_lists_patterns(user_id):
                await delete_pattern(self.redis, pattern)

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
                        _enhancer(),
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
                **prompt_fields(record),
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
                            DfEngineGenerations.raw_prompt,  # type: ignore
                            DfEngineGenerations.finalized_prompt,  # type: ignore
                            DfEngineGenerations.enhance_id,  # type: ignore
                            DfEngineGenerations.cost,  # type: ignore
                        )
                        .selectinload(DfEngineGenerations.model_option)  # type: ignore
                        .load_only(DfEngineModelOptions.name),  # type: ignore
                        selectinload(DfEngineGenerationResults.generation)
                        .selectinload(  # type: ignore
                            DfEngineGenerations.enhancer  # type: ignore
                        )
                        .load_only(DfEngineGenerations.raw_prompt, DfEngineGenerations.finalized_prompt),  # type: ignore
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
                            DfEngineGenerations.raw_prompt,  # type: ignore
                            DfEngineGenerations.finalized_prompt,  # type: ignore
                            DfEngineGenerations.enhance_id,  # type: ignore
                            DfEngineGenerations.cost,  # type: ignore
                        )
                        .selectinload(DfEngineGenerations.model_option)  # type: ignore
                        .load_only(DfEngineModelOptions.name),  # type: ignore
                        selectinload(DfEngineGenerationResults.generation)
                        .selectinload(  # type: ignore
                            DfEngineGenerations.enhancer  # type: ignore
                        )
                        .load_only(DfEngineGenerations.raw_prompt, DfEngineGenerations.finalized_prompt),  # type: ignore
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
            "Returns a page of the current (main) file version of every image or video (`type`, default video) "
            "generated on this task; "
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
        type: Literal["image", "video"] = Query("video", description="Which kind of files to list."),
        search: Optional[str] = Query(
            None,
            min_length=1,
            description=(
                "Prefix search across the generation prompt, model name, and file name. "
                "Leave empty to return all files."
            ),
        ),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=100, ge=1, le=100, description="Number of files to return per page."),
    ) -> Response:
        response = Response()
        user_id = int(self.user["user_id"])
        can_override = has_override(self.user["roles"])
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        kinds = ("image", "image_edit") if type == "image" else ("video",)
        try:
            project_task = await get_project_task(ctx, task_uid)
            task_id = project_task["id"] if project_task["is_song"] is False else None
            song_id = project_task["id"] if project_task["is_song"] is True else None

            if search:
                main_generations = await search_task_generations(
                    str(task_uid), search, user_id, can_override, my_task, kinds
                )
                await overlay_favourites(ctx, main_generations, user_id)
                await overlay_prompts(ctx, main_generations)
            else:
                main_generations = await get_generation_main_refactored(
                    ctx=ctx,
                    viewer_id=user_id,
                    project_id=project_task["project_id"],
                    task_id=task_id,
                    song_id=song_id,
                    personal_file=my_task,
                    has_override=can_override,
                )
                main_generations = [g for g in main_generations if g["kind"] in kinds]
            for generation in main_generations:
                generation.pop("references", None)
                generation.pop("variants", None)
                generation.pop("is_main", None)
                generation.pop("raw_prompt", None)
                generation.pop("finalized_prompt", None)
                generation.pop("version", None)
                generation.pop("parent_id", None)

            start = (page - 1) * itemsPerPage
            response.data = PaginationResponse(
                paginated=main_generations[start : start + itemsPerPage], totalData=len(main_generations)
            )
            logging.info(
                f"user={user_id} fetched user galleries task_uid={task_uid} my_task={my_task} type={type} "
                f"search={search} page={page} total={len(main_generations)}"
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
            variants = await get_generation_main_variants(ctx, file_uid, user_id, has_override(self.user["roles"]))
            target = next((variant for variant in variants if variant["file_uid"] == str(file_uid)), None)
            if not target:
                raise DataNotFoundError(message="main_generation_file_not_found")

            if target["is_main"]:
                response.data = await get_generation_main_file_detail(
                    ctx, file_uid, user_id, has_override(self.user["roles"])
                )
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
