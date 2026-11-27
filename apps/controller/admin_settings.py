import json
import traceback
from uuid import UUID
from typing import Any, Optional
from fastapi import status, Query, Request, Path
from fastapi_controller import controller
from sqlalchemy import func
from sqlalchemy.orm import selectinload, load_only
from apps.controller.core import CoreDependencies
from schemas.response import PaginationResponse, Response
from schemas.format.admin_setting_logs import SettingLogRecord
from schemas.payload.admin_settings import (
    AdminGlobalSettingPayload,
    ProjectClassLimitations,
    ProjectSettingPayload,
    PromptValidationType,
)
from log import logging
from error import ServiceError, BaseError, DataNotFoundError, DataValidationError
from utils import local_time
from services.mysql import query
from services.mysql.model import (
    DfEngineSettings,
    DfEngineSettingLogs,
    DfEngineModelOptions,
    Users,
    Employees,
    Projects,
    ProjectClasses,
    DfEngineProjectSettings,
)
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.redis import get_json, set_json, delete_pattern


SETTING_CODE = "admin_setting"


class SettingController(CoreDependencies):
    @controller.get(
        "/setting/logs",
        summary="Get settings logs.",
        description=(
            "Returns the settings change history, newest first: who saved each change, "
            "the settings before and after, and which sections actually moved. Only "
            "real changes are recorded — saving without changing anything doesn't add "
            "an entry. Paginated, and searchable by the saver's name."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Admin Settings"],
        response_model=Response,
    )
    async def admin_settings_to_fetch_settings_logs(
        self,
        search: Optional[str] = Query(None, description="Filter by the saver's name."),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        try:
            key = self.cache_key.setting_log_refactored(page, itemsPerPage, search)
            cached = await get_json(self.redis, key)
            if cached is not None:
                logging.info(
                    f"user={self.user['user_id']} listed setting logs page={page} size={itemsPerPage} source=cache"
                )
                response.data = PaginationResponse(paginated=cached["logs"], totalData=cached["total_data"])
                return response

            filters = (DfEngineSettingLogs.user_name.ilike(f"%{search}%"),) if search else None  # type: ignore

            total_data = await self.admin_repo.get_setting_log(
                columns=(func.count(DfEngineSettingLogs.id),),  # type: ignore
                filters=filters,
                raise_if_null=False,
            )

            records = await self.admin_repo.get_setting_log(
                options=(
                    selectinload(DfEngineSettingLogs.created_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                ),
                filters=filters,
                order_by=(DfEngineSettingLogs.created_at.desc(), DfEngineSettingLogs.id.desc()),  # type: ignore
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
                fetch_one=False,
                raise_if_null=False,
            )

            logs = [SettingLogRecord.format(record).model_dump() for record in records]

            await set_json(self.redis, key, {"logs": logs, "total_data": total_data})
            logging.info(
                f"user={self.user['user_id']} listed setting logs page={page} size={itemsPerPage} "
                f"count={len(logs)} total={total_data} source=database"
            )
            response.data = PaginationResponse(paginated=logs, totalData=total_data)
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not list setting logs (page {page}): {e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error listing setting logs\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.get(
        "/setting",
        summary="Get settings.",
        description=(
            "Shows the current DF Engine settings for the whole workspace: the generate "
            "and enhance limits, the storyboard and prompt limits, how much of the earlier "
            "chat the assistant remembers, the limits for each project class, and which "
            "model runs the assistant. These start from sensible defaults, so the "
            "settings page always has something to show."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Admin Settings"],
        response_model=Response,
    )
    async def admin_settings_to_fetch_global_settings(self) -> Response:
        response = Response()
        try:
            key = self.cache_key.setting_global_refactored()
            settings = await get_json(self.redis, key)
            source = "cache"
            if settings is None:
                records = await self.admin_repo.get_setting(
                    filters=(DfEngineSettings.code == SETTING_CODE,),  # type: ignore
                    fetch_one=False,
                    raise_if_null=False,
                )
                settings = {record["key"]: record["value"] for record in records}
                await set_json(self.redis, key, settings)
                source = "database"
            logging.info(
                f"user={self.user['user_id']} fetched admin global setting count={len(settings)} source={source}"
            )
            response.data = settings
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not fetch admin global setting: {e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error fetching admin global setting\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.post(
        "/setting",
        summary="Update settings.",
        description=(
            "Saves the workspace-wide settings: the folder depth limit, chat assistant "
            "limits, usage limits per project class, prompt guardrails, and which model "
            "powers the assistant. Send the whole settings document each time — this replaces "
            "what's saved, it isn't a partial update. Any real change is recorded in "
            "the history together with who made it."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Admin Settings"],
        response_model=Response,
    )
    async def admin_settings_to_update_global_settings(
        self,
        schema: AdminGlobalSettingPayload,
        request: Request,
    ) -> Response:
        response = Response()
        try:
            assistant_model = None
            if schema.assistant_model is not None:
                model = await self.model_option_repo.get_model(
                    columns=(
                        DfEngineModelOptions.id,
                        DfEngineModelOptions.uid,
                        DfEngineModelOptions.model_id,
                        DfEngineModelOptions.name,
                        DfEngineModelOptions.type,
                        DfEngineModelOptions.is_enabled,
                        DfEngineModelOptions.is_available,
                        DfEngineModelOptions.top_provider,
                    ),
                    filters=(DfEngineModelOptions.uid == str(schema.assistant_model),),  # type: ignore
                )
                if model["type"] != ModelUsageTypes.text:
                    raise DataValidationError(message="setting_engine_model_must_be_text")
                if not model["is_enabled"]:
                    raise DataValidationError(message="setting_engine_model_must_be_enabled")
                if not model["is_available"]:
                    raise DataValidationError(message="setting_engine_model_must_be_available")
                assistant_model = {k: model[k] for k in ("id", "uid", "model_id", "name", "top_provider")}

            project_classes = await query(
                db=self.db,
                table=ProjectClasses,
                options=(load_only(ProjectClasses.id, ProjectClasses.name, ProjectClasses.color),),  # type: ignore
            )
            class_by_id = {pc.id: pc for pc in project_classes}
            unknown_class_fields = {
                f"project_class_limitations.{index}.id": ["project_class_not_found"]
                for index, pcl in enumerate(schema.project_class_limitations)
                if pcl.id not in class_by_id
            }
            if unknown_class_fields:
                raise DataNotFoundError(message="project_class_not_found", error=unknown_class_fields)

            setting_filters = (DfEngineSettings.code == SETTING_CODE,)
            records = await self.admin_repo.get_setting(
                filters=setting_filters,  # type: ignore
                fetch_one=False,
                raise_if_null=False,
            )
            saved = {record["key"]: record["value"] for record in records}

            saved_limits = {
                item["id"]: item
                for item in saved.get("project_class_limitations") or []
                if isinstance(item, dict) and "id" in item
            }
            requested_limits = {pcl.id: pcl.model_dump(mode="json") for pcl in schema.project_class_limitations}

            if "prompt_guardrails" not in schema.model_fields_set:
                kept = [
                    rule
                    for rule in saved.get("prompt_guardrails") or []
                    if rule.get("type") in PromptValidationType.__args__
                ]
                prompt_guardrails = kept or None
            else:
                prompt_guardrails = (
                    [v.model_dump(mode="json") for v in schema.prompt_guardrails]
                    if schema.prompt_guardrails is not None
                    else None
                )

            incoming = {
                "folder_depth_limit": schema.folder_depth_limit,
                "chat_assistant_settings": schema.chat_assistant_settings.model_dump(mode="json"),
                "assistant_model": assistant_model,
                "prompt_guardrails": prompt_guardrails,
                "project_class_limitations": [
                    {
                        **ProjectClassLimitations(id=pc.id).model_dump(mode="json"),
                        **(saved_limits.get(pc.id) or {}),
                        **requested_limits.get(pc.id, {}),
                        "id": pc.id,
                        "name": pc.name,
                        "color": pc.color,
                    }
                    for pc in project_classes
                ],
            }
            stale_keys = [key for key in saved if key not in incoming]
            if stale_keys:
                await self.admin_repo.delete(
                    filters=(*setting_filters, DfEngineSettings.key.in_(stale_keys)),  # type: ignore
                )

            previous = {key: value for key, value in saved.items() if key in incoming}
            now = local_time()
            for key, value in incoming.items():
                if key in previous and previous[key] != value:
                    await self.admin_repo.update(
                        filters=(*setting_filters, DfEngineSettings.key == key),  # type: ignore
                        values={"value": json.dumps(value), "updated_at": now},
                    )
            await self.admin_repo.create(
                [
                    {"code": SETTING_CODE, "key": key, "value": json.dumps(value), "created_at": now}
                    for key, value in incoming.items()
                    if key not in previous
                ]
            )

            changed = bool(previous) and previous != incoming
            if changed:
                user_row = await self.user_repo.get_user(
                    columns=(Users.email, Users.username),
                    filters=(Users.id == int(self.user["user_id"]),),  # type: ignore
                    raise_if_null=False,
                )
                await self.admin_repo.create_setting_log(
                    {
                        "created_by": int(self.user["user_id"]),
                        "user_email": user_row["email"] if user_row else None,
                        "user_name": user_row["username"] if user_row else None,
                        "previous_data": previous,
                        "incoming_data": incoming,
                        "ip_address": (
                            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                            or (request.client.host if request.client else None)
                        ),
                        "user_agent": request.headers.get("User-Agent"),
                    }
                )

            await self.db.flush()
            await delete_pattern(self.redis, self.cache_key.setting_pattern())
            logging.info(f"user={self.user['user_id']} saved admin global setting changed={changed}")

            response.data = incoming
        except BaseError as e:
            logging.warning(f"user={self.user['user_id']} could not save admin setting: {e.message} ({e.status_code})")
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error saving admin setting\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.get(
        "/setting/{uid}",
        summary="Get project setting.",
        description=(
            "Returns the generation limits currently in effect for one project — its "
            "spend cap and various content-length limits, plus the usage percentage "
            "that should trigger a warning. Uses the project's own saved override if "
            "it has one, otherwise falls back to the default for its project class. "
            "Requires the global settings to have been configured at least once and "
            "the project to be assigned to a class."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Admin Settings"],
        response_model=Response,
    )
    async def df_engine_with_uid_to_fetch_project_setting(
        self, uid: UUID = Path(..., description="Project UID.")
    ) -> Response:
        response = Response()
        PROJECT_SETTING_LIMIT_FIELDS = (
            "token_usage_limit",
            "compose_input_max_chars",
            "storyboard_prompt_chars",
            "max_scene_per_storyboard",
            "max_shot_per_scene",
            "token_limit_threshold",
        )
        try:
            key = self.cache_key.setting_project_refactored(uid)
            data = await get_json(self.redis, key)
            source = "cache"
            if data is None:
                project = await self.project_repo.get_project(
                    columns=(Projects.id, Projects.name, Projects.classification, Projects.project_class_id),
                    filters=(Projects.uid == str(uid),),  # type: ignore
                )

                limits = await self.project_setting_repo.get_project_setting(
                    columns=tuple(getattr(DfEngineProjectSettings, field) for field in PROJECT_SETTING_LIMIT_FIELDS),
                    filters=(DfEngineProjectSettings.project_id == project["id"],),  # type: ignore
                    raise_if_null=False,
                )
                if limits is None:
                    if project["project_class_id"] is None:
                        raise DataValidationError(message="project_class_not_assigned")
                    class_limits = await self.admin_repo.get_setting(
                        filters=(
                            DfEngineSettings.code == SETTING_CODE,  # type: ignore
                            DfEngineSettings.key == "project_class_limitations",  # type: ignore
                        ),
                        raise_if_null=False,
                    )
                    if class_limits is None or class_limits["value"] is None:
                        raise DataValidationError(message="global_setting_not_configured")
                    class_limit = next(
                        (item for item in class_limits["value"] if item.get("id") == project["project_class_id"]),
                        None,
                    )
                    if class_limit is None:
                        raise DataNotFoundError(message="project_class_limitation_not_found")
                    limits = {field: class_limit.get(field) for field in PROJECT_SETTING_LIMIT_FIELDS}

                data = {"project": project["name"], "classification": project["classification"], **limits}
                await set_json(self.redis, key, data)
                source = "database"
            logging.info(f"user={self.user['user_id']} fetched project setting uid={uid} source={source}")
            response.data = data
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not fetch project setting uid={uid}: {e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error fetching project setting uid={uid}\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.post(
        "/setting/{uid}",
        summary="Upsert project setting.",
        description=(
            "Saves a per-project override of the generation limits (spend cap, content "
            "length limits, and the warning threshold), replacing whatever this project "
            "had before. While the override exists, this project uses these values "
            "instead of its project class defaults. Any field left out falls back to a "
            "standard default."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Admin Settings"],
        response_model=Response,
    )
    async def df_engine_with_uid_to_save_project_setting(
        self,
        schema: ProjectSettingPayload,
        uid: UUID = Path(..., description="Project UID."),
    ) -> Response:
        response = Response()
        try:
            project = await self.project_repo.get_project(
                columns=(Projects.id, Projects.name, Projects.classification),
                filters=(Projects.uid == str(uid),),  # type: ignore
            )

            user_id = int(self.user["user_id"])
            values = schema.model_dump()

            now = local_time()
            await self.project_setting_repo.upsert(
                {
                    **values,
                    "project_id": project["id"],
                    "created_at": now,
                    "created_by": user_id,
                    "updated_at": now,
                    "updated_by": user_id,
                }
            )
            await self.db.commit()
            data = {"project": project["name"], "classification": project["classification"], **values}
            await set_json(self.redis, self.cache_key.setting_project_refactored(uid), data)
            logging.info(f"user={self.user['user_id']} saved project setting uid={uid}")
            response.data = data
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not save project setting uid={uid}: {e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error saving project setting uid={uid}\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response
