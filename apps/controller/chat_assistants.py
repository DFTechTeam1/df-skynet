import json
import traceback
from uuid import UUID, uuid4
from sqlalchemy import func
from sqlalchemy.orm import load_only, selectinload
from fastapi import Form, Path, Query, Request, status
from fastapi_controller import controller
from error import ServiceError, BaseError, RateLimitedError, DataNotFoundError, DataValidationError
from apps.controller.core import CoreDependencies
from error import BaseError, ServiceError
from log import logging
from schemas.payload.chat_assistants import CreateNewSessionPayload
from middlewares.lang import resolve_message
from services.mysql import get_usd_rate
from services.openrouter import call_prompt_guardrail
from schemas.response import Response
from utils.formatter import format_udin_url
from services.mysql.model.df_engine_generations import GenerationKinds
from services.mysql.model import (
    PROJECT_STATUS_ONGOING,
    Projects,
    DfEngineMenus,
    DfEngineProjectSettings,
    DfEngineSettings,
    ProjectPersonInCharges,
    Employees,
    DfEngineApiKeys,
    DfEngineChatAssistants,
    DfEngineChatSessions,
    DfEngineGenerations,
    TransferTeamMembers,
    Users,
    DfEngineUploadFiles,
    DfEngineGenerationResults,
    DfEngineGuardrailValidations,
)


CHAT_GUARDRAIL_TYPES = ["prompt_injection", "nfsw", "chat_assistant"]


class ChatAssistantsController(CoreDependencies):
    @controller.get(
        "/projects/{project_uid}/chat-assistants/{menu_uid}",
        summary="Get list chat sessions.",
        description="test.",
        status_code=status.HTTP_200_OK,
        tags=["Chat Assistants"],
        response_model=Response,
    )
    async def chat_assistants_with_project_uid_and_menu_uid_to_get_list_sessions(self) -> Response:
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
        "/projects/{project_uid}/chat-assistants/{menu_uid}/new",
        summary="Create new session.",
        description="test.",
        status_code=status.HTTP_200_OK,
        tags=["Chat Assistants"],
        response_model=Response,
    )
    async def chat_assistants_with_project_uid_and_menu_uid_to_create_new_session(
        self,
        schema: CreateNewSessionPayload,
        project_uid: UUID = Path(...),
        menu_uid: UUID = Path(...),
    ) -> Response:
        response = Response()
        limit_api_key = None
        assistant_model = None
        prompt_guardrails = None
        global_project_settings = None
        project_setting = None
        project_api_key = None
        prompt_validations = []
        uploaded_files = None
        generated_results = None
        attachment_errors = None
        log_prefix = f"[chat-assistant:new] user={self.user['user_id']} project={project_uid} menu={menu_uid}"

        try:
            logging.info(f"{log_prefix} creating new chat session")

            # Load admin settings (assistant model, guardrails, global class limits)
            admin_settings = await self.admin_repo.get_setting(
                filters=(
                    DfEngineSettings.key.in_(["assistant_model", "prompt_guardrails", "project_class_limitations"]),  # type: ignore
                ),
                fetch_one=False,
            )
            for setting in admin_settings:
                if setting["key"] == "assistant_model":
                    assistant_model = setting["value"]
                if setting["key"] == "prompt_guardrails":
                    prompt_guardrails = setting["value"]
                if setting["key"] == "project_class_limitations":
                    global_project_settings = setting["value"]
                    break

            # Assistant model must be configured
            if not assistant_model:
                logging.warning(f"{log_prefix} assistant_model is not configured in admin settings")
                raise DataValidationError(message="default_model_not_configured", context={"model": "assistant"})

            # Load project with its PICs, their main API keys, and approved transfers
            project = await self.project_repo.get_project(
                filters=(Projects.uid == str(project_uid),),
                columns=(Projects,),
                options=(
                    load_only(Projects.id, Projects.status, Projects.project_class_id),  # type: ignore
                    selectinload(Projects.project_setting).load_only(  # type: ignore
                        DfEngineProjectSettings.token_usage_limit,  # type: ignore
                        DfEngineProjectSettings.token_limit_threshold,  # type: ignore
                    ),
                    selectinload(Projects.project_person_in_charges)  # type: ignore
                    .load_only(
                        ProjectPersonInCharges.pic_id,  # type: ignore
                        ProjectPersonInCharges.is_lead,  # type: ignore
                    )
                    .selectinload(ProjectPersonInCharges.pic)  # type: ignore
                    .load_only(Employees.boss_id, Employees.nickname)  # type: ignore
                    .selectinload(
                        Employees.api_keys.and_(DfEngineApiKeys.is_main.is_(True))  # type: ignore
                    )
                    .load_only(
                        DfEngineApiKeys.employee_id,  # type: ignore
                        DfEngineApiKeys.key,  # type: ignore
                    ),
                    selectinload(
                        Projects.transfer_team_members.and_(TransferTeamMembers.status == 2)  # type: ignore
                    ).load_only(
                        TransferTeamMembers.employee_id,  # type: ignore
                        TransferTeamMembers.requested_by,  # type: ignore
                    ),
                ),
            )

            logging.info(
                f"{log_prefix} project loaded: id={project['id']} status={project['status']} "
                f"class_id={project['project_class_id']} "
                f"pics={len(project['project_person_in_charges'])} "
                f"approved_transfers={len(project['transfer_team_members'])}"
            )

            # Project must have a class (drives the token limit)
            if not project["project_class_id"]:
                logging.warning(f"{log_prefix} project has no project class")
                raise DataValidationError(message="project_class_not_assigned")

            # Project must be ongoing
            if project["status"] != PROJECT_STATUS_ONGOING:
                logging.warning(f"{log_prefix} project status={project['status']} is not ongoing")
                raise DataValidationError(
                    message="project_action_requires_ongoing",
                    context={"action": "Chat assistant"},
                )

            # Project must have at least one PIC
            if not project["project_person_in_charges"]:
                logging.warning(f"{log_prefix} project has no PIC")
                raise DataValidationError(message="project_pic_not_assigned")

            # Project must have exactly one lead
            project_leads = [pic for pic in project["project_person_in_charges"] if pic["is_lead"]]
            if not project_leads:
                logging.warning(f"{log_prefix} project has no lead PIC")
                raise DataValidationError(message="project_lead_not_assigned")

            if len(project_leads) > 1:
                logging.warning(
                    f"{log_prefix} project has {len(project_leads)} leads: "
                    f"pic_ids={[lead['pic_id'] for lead in project_leads]}"
                )
                raise DataValidationError(
                    message="project_lead_multiple",
                    context={"total_lead": len(project_leads)},
                )

            # Lead must have exactly one main API key
            project_lead = project_leads[0]
            lead_pic = project_lead["pic"]
            if not lead_pic["api_keys"]:
                logging.warning(
                    f"{log_prefix} lead pic_id={lead_pic['id']} ({lead_pic['nickname']}) has no main API key"
                )
                raise DataValidationError(
                    message="project_lead_api_key_not_found",
                    context={"nickname": lead_pic["nickname"]},
                )

            if len(lead_pic["api_keys"]) > 1:
                logging.warning(
                    f"{log_prefix} lead pic_id={lead_pic['id']} ({lead_pic['nickname']}) has "
                    f"{len(lead_pic['api_keys'])} main API keys"
                )
                raise DataValidationError(
                    message="project_lead_api_key_multiple",
                    context={"nickname": lead_pic["nickname"], "total_key": len(lead_pic["api_keys"])},
                )

            # Main API key per PIC, keyed by employee id
            pic_api_keys = {
                pic["pic_id"]: pic["pic"]["api_keys"][0]
                for pic in project["project_person_in_charges"]
                if pic["pic"]["api_keys"]
            }
            lead_api_key = lead_pic["api_keys"][0]
            logging.info(
                f"{log_prefix} lead resolved: pic_id={lead_pic['id']} ({lead_pic['nickname']}) "
                f"lead_key_owner={lead_api_key['employee_id']} pics_with_key={list(pic_api_keys.keys())}"
            )

            # Token limit: project setting first, else the global limit of the project class
            project_setting = project["project_setting"]
            if project_setting:
                limit_api_key = project_setting["token_usage_limit"] * project_setting["token_limit_threshold"]
                limit_source = "project_setting"
            else:
                if not global_project_settings:
                    logging.warning(f"{log_prefix} no project setting and no global project class limitations")
                    raise DataValidationError(message="global_project_setting_not_configured")
                for setting in global_project_settings:
                    if setting["id"] == project["project_class_id"]:
                        limit_api_key = setting["token_usage_limit"] * setting["token_limit_threshold"]
                        break
                else:
                    logging.warning(f"{log_prefix} no global limit for project_class_id={project['project_class_id']}")
                    raise DataValidationError(message="project_class_limitation_not_found")
                limit_source = f"global_class_{project['project_class_id']}"
            logging.info(f"{log_prefix} token limit={limit_api_key} source={limit_source}")

            # Menu must exist
            await self.menu_repo.get_menu(filters=(DfEngineMenus.uid == str(menu_uid),))

            # Load the current user with their employee
            get_user = await self.user_repo.get_user(
                filters=(Users.id == int(self.user["user_id"]),),
                columns=(Users,),
                options=(
                    load_only(Users.id, Users.username),  # type: ignore
                    selectinload(Users.employees).load_only(Employees.boss_id),  # type: ignore
                ),
            )

            # User must be registered as an employee
            if not get_user["employees"]:
                logging.warning(f"{log_prefix} user has no linked employee")
                raise DataValidationError(message="employee_not_found")

            employee_id = get_user["employees"]["id"]
            boss_id = get_user["employees"]["boss_id"]

            # Own key: the user is a PIC on this project (e.g. PM or Director)
            key_source = "own"
            project_api_key = pic_api_keys.get(employee_id)

            # Transferred: the user was moved into this project, so use the requester's key
            if not project_api_key:
                requested_by_map = {
                    member["employee_id"]: member["requested_by"] for member in project["transfer_team_members"]
                }
                if employee_id in requested_by_map:
                    project_api_key = pic_api_keys.get(requested_by_map[employee_id])
                    key_source = f"transfer_requester_{requested_by_map[employee_id]}"

            # Boss: use the user's direct boss's key
            if not project_api_key and boss_id:
                project_api_key = pic_api_keys.get(boss_id)
                key_source = f"boss_{boss_id}"

            # Lead: use the project lead's key as the final fallback
            if not project_api_key:
                project_api_key = lead_api_key
                key_source = f"lead_{lead_pic['id']}"

            logging.info(
                f"{log_prefix} api key resolved: employee_id={employee_id} boss_id={boss_id} "
                f"source={key_source} key_owner={project_api_key['employee_id']}"
            )

            # Chat cost already spent on this project
            chat_cost = await self.chat_assistant_repo.get_chat_assistant(
                columns=(
                    DfEngineChatSessions.project_id,
                    func.coalesce(func.sum(DfEngineChatAssistants.cost), 0).label("total_cost"),
                ),
                joins=((DfEngineChatSessions, DfEngineChatSessions.id == DfEngineChatAssistants.session_id),),
                filters=(DfEngineChatSessions.project_id == project["id"],),
                group_by=(DfEngineChatSessions.project_id,),
                raise_if_null=False,
            )
            chat_spent = chat_cost["total_cost"] if chat_cost else 0

            # Generation cost already spent on this project
            generation_cost = await self.generation_repo.get_generation(
                columns=(
                    DfEngineGenerations.project_id,
                    func.coalesce(func.sum(DfEngineGenerations.cost), 0).label("total_cost"),
                ),
                filters=(DfEngineGenerations.project_id == project["id"],),
                group_by=(DfEngineGenerations.project_id,),
                raise_if_null=False,
            )
            generation_spent = generation_cost["total_cost"] if generation_cost else 0

            total_spent = chat_spent + generation_spent
            logging.info(
                f"{log_prefix} cost spent on project: chat={chat_spent} generation={generation_spent} "
                f"total={total_spent}"
            )

            # Project must still be within its cost limit
            if total_spent > limit_api_key:
                logging.warning(
                    f"{log_prefix} cost limit exceeded: spent={total_spent} limit={limit_api_key} source={limit_source}"
                )
                raise DataValidationError(
                    message="project_cost_limit_exceeded",
                    context={"spent": f"${total_spent:.2f}", "limit": f"${limit_api_key:.2f}"},
                )

            # Keep only the enabled (threshold > 0) guardrails this chat should validate against
            if prompt_guardrails:
                for prompt in prompt_guardrails:
                    if prompt["type"] in CHAT_GUARDRAIL_TYPES:
                        prompt_validations.append(prompt)

            logging.info(f"{log_prefix} guardrails to validate: {[prompt['type'] for prompt in prompt_validations]}")

            # Get attachment uid
            if schema.attachments:
                uploaded_files = [str(a.file_uid) for a in schema.attachments if a.type == "upload"]
                generated_results = [str(a.file_uid) for a in schema.attachments if a.type == "generated"]

            #  Get uploaded files
            if uploaded_files:
                uploaded_files = await self.uploaded_file_repo.get_uploaded_file(
                    filters=(
                        DfEngineUploadFiles.uid.in_(uploaded_files),  # type: ignore
                        DfEngineUploadFiles.type.in_(["image"]),  # type: ignore
                    ),
                    raise_if_null=False,
                    fetch_one=False,
                )

            # Get generated results
            if generated_results:
                generated_results = await self.generation_result_repo.get_generation_file(
                    joins=(DfEngineGenerationResults.generation,),  # type: ignore
                    filters=(
                        DfEngineGenerationResults.uid.in_(generated_results),  # type: ignore
                        DfEngineGenerations.kind.in_([GenerationKinds.image, GenerationKinds.image_edit]),  # type: ignore
                    ),
                    raise_if_null=False,
                    fetch_one=False,
                )

            # Every attachment the client sent must exist; report each missing one by its own index.
            found = {
                "upload": {f["uid"] for f in uploaded_files or []},  # type: ignore
                "generated": {f["uid"] for f in generated_results or []},  # type: ignore
            }
            attachment_errors = {
                f"attachments.{idx}": [
                    "uploaded_file_not_found" if a.type == "upload" else "generation_result_not_found"
                ]
                for idx, a in enumerate(schema.attachments)
                if str(a.file_uid) not in found[a.type]
            }
            if attachment_errors:
                logging.warning(f"{log_prefix} attachments not found: {list(attachment_errors)}")
                raise DataNotFoundError(message="file_not_found", error=attachment_errors)

            # Merge both sources into one list; `type` keeps them distinguishable.
            user_attachments = [
                {**f, "type": attachment_type, "path": format_udin_url(f["path"])}  # type: ignore
                for attachment_type, files in (("upload", uploaded_files), ("generated", generated_results))
                for f in files or []
            ]

            session_uid = str(uuid4())

            guardrail_response = None

            if prompt_validations:
                log_row = {
                    "apikeyable_id": project_api_key["id"],
                    "apikeyable_type": DfEngineApiKeys.__name__,
                    "model_id": assistant_model["id"],
                    "created_by": self.user["user_id"],
                }
                try:
                    guardrail_response = await call_prompt_guardrail(
                        schema.content,
                        project_api_key["key"],
                        prompt_validations,
                        assistant_model["model_id"],
                        self.user["user_id"],
                    )
                except ServiceError as exc:
                    ctx = exc.context or {}
                    self.db.add(
                        DfEngineGuardrailValidations(
                            **log_row,
                            message=resolve_message(exc.message),
                            payload=ctx.get("payload") or {},
                            response={"error": exc.error, "upstream_body": ctx.get("upstream_body")},
                            status_code=(exc.error or {}).get("upstream_status", exc.status_code),
                            exchange_rate=await self.db.run_sync(get_usd_rate),
                        )
                    )
                    await self.db.commit()
                    raise

                body = guardrail_response.json()
                usage = body.get("usage") or {}
                self.db.add(
                    DfEngineGuardrailValidations(
                        **log_row,
                        message="Success",
                        payload=json.loads(guardrail_response.request.content),
                        response=body,
                        status_code=guardrail_response.status_code,
                        total_tokens=usage.get("total_tokens") or 0,
                        cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                        cost=usage.get("cost") or 0,  # type: ignore
                        exchange_rate=await self.db.run_sync(get_usd_rate),
                    )
                )
                await self.db.flush()

            response.data = guardrail_response.json() if guardrail_response else None
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/chat-assistants/{session_uid}",
        summary="Update chat sessions topic.",
        description="test.",
        status_code=status.HTTP_200_OK,
        tags=["Chat Assistants"],
        response_model=Response,
    )
    async def chat_assistants_with_session_uid_to_update_topic(self) -> Response:
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
        "/chat-assistants/{session_uid}",
        summary="Continue chat to specific session.",
        description="test.",
        status_code=status.HTTP_200_OK,
        tags=["Chat Assistants"],
        response_model=Response,
    )
    async def chat_assistants_with_session_uid_to_continue_chat_session(self) -> Response:
        response = Response()
        try:
            pass
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/chat-assistants/{session_uid}/archieve",
        summary="Archieve specific chat session.",
        description="test.",
        status_code=status.HTTP_200_OK,
        tags=["Chat Assistants"],
        response_model=Response,
    )
    async def chat_assistants_with_session_uid_to_archieve_chat_session(self) -> Response:
        response = Response()
        try:
            pass
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/chat-assistants/{session_uid}/resend/{chat_uid}",
        summary="Resend bubble chat.",
        description="test.",
        status_code=status.HTTP_200_OK,
        tags=["Chat Assistants"],
        response_model=Response,
    )
    async def chat_assistants_with_session_uid_to_resend_chat_inside_chat_session(self) -> Response:
        response = Response()
        try:
            pass
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
