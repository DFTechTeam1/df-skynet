import traceback
from uuid import UUID
from sqlalchemy.orm import load_only, selectinload
from fastapi import Form, Path, Query, Request, status
from fastapi_controller import controller
from error import ServiceError, BaseError, RateLimitedError, DataNotFoundError, DataValidationError
from apps.controller.core import CoreDependencies
from error import BaseError, ServiceError
from log import logging
from schemas.response import Response
from services.repository.projects import ProjectRepository
from services.repository.menus import MenuRepository
from services.repository.settings import AdminSettingRepository
from services.mysql.model import Projects, DfEngineMenus, DfEngineProjectSettings, DfEngineSettings


PROJECT_STATUS_ONGOING = 1


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
        self, project_uid: UUID = Path(...), menu_uid: UUID = Path(...)
    ) -> Response:
        response = Response()
        project_repo = ProjectRepository(self.db)
        menu_repo = MenuRepository(self.db)
        admin_repo = AdminSettingRepository(self.db)

        limit_api_key = None
        assistant_model = None
        prompt_guardrails = None
        global_project_settings = None
        project_setting = None

        try:
            # Get Admin Setting
            admin_settings = await admin_repo.get_setting(
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

            if not assistant_model:
                raise DataValidationError(message="default_model_not_configured", context={"model": "assistant"})

            # Get Project
            project = await project_repo.get_project(
                filters=(Projects.uid == str(project_uid),),
                columns=(Projects,),
                options=(
                    load_only(Projects.id, Projects.status, Projects.project_class_id),  # type: ignore
                    selectinload(Projects.project_setting).load_only(  # type: ignore
                        DfEngineProjectSettings.token_usage_limit,  # type: ignore
                        DfEngineProjectSettings.token_limit_threshold,  # type: ignore
                    ),
                ),
            )

            if not project["project_class_id"]:
                raise DataValidationError(message="project_class_not_assigned")

            if project["status"] != PROJECT_STATUS_ONGOING:
                raise DataValidationError(
                    message="project_action_requires_ongoing",
                    context={"action": "Chat assistant"},
                )

            if project_setting:
                limit_api_key = (
                    project["project_setting"]["token_usage_limit"]
                    * project["project_setting"]["token_limit_threshold"]
                )
            else:
                if not global_project_settings:
                    raise DataValidationError(message="global_project_setting_not_configured")
                for setting in global_project_settings:
                    if setting["id"] == project["project_class_id"]:
                        limit_api_key = setting["token_usage_limit"] * setting["token_limit_threshold"]
                        break

            print(limit_api_key)

            # Get Menu
            await menu_repo.get_menu(filters=(DfEngineMenus.uid == str(menu_uid),))

            response.data = project
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
