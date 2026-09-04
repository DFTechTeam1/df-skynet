import json
import traceback
from uuid import UUID
from typing import Optional
from fastapi import status, Query, Request, Path
from fastapi_controller import controller
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import PaginationResponse, Response
from schemas.payload.setting import AdminGlobalSettingPayload, ProjectClassLimitations, ProjectSettingPayload
from log import logging
from error import ServiceError, BaseError, DataNotFoundError, DataValidationError
from utils import local_time
from utils.formatter import format_datetime, format_user_employees
from utils.serializer import serialize
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
from services.redis import get_json, set_json, delete_pattern, CacheKeys


SETTING_CODE = "admin_setting"


class SettingController(CoreDependencies):
    @controller.get(
        "/setting/logs",
        summary="View the history of changes made to the DF Engine settings.",
        description=(
            "Returns the settings audit trail, newest first: every time the settings "
            "were saved with an actual change, this lists who saved it (`creator`), the "
            "settings as they were right before that save (`previous_data`) next to what "
            "they became (`incoming_data`), and `changed_fields` — the top-level "
            "sections that actually differ between the two, so the UI can highlight what "
            "moved. `previous_data` is null for the very first save, since there's "
            "nothing to compare against, and a save that changed nothing is not recorded "
            "here at all. Paginated — pass `page` and `itemsPerPage` to page through the "
            "history, and `search` to filter by the saver's name."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def df_engine_fetch_global_setting_logs(
        self,
        search: Optional[str] = Query(None, description="Filter by the saver's name (prefix match)."),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            logs_cache_key = cache_key.setting_logs_pagination(page, itemsPerPage, search)
            cached = await get_json(self.redis, logs_cache_key)
            if cached is not None:
                logging.info(
                    f"user={self.user['user_id']} listed setting logs page={page} size={itemsPerPage} source=cache"
                )
                response.data = PaginationResponse(paginated=cached["logs"], totalData=cached["total_data"])
                return response

            filters = (DfEngineSettingLogs.user_name.ilike(f"{search}%"),) if search else None  # type: ignore

            total_data = (
                await query(
                    db=self.db,
                    table=DfEngineSettingLogs,
                    columns=(func.count(DfEngineSettingLogs.id),),  # type: ignore
                    filters=filters,
                    fetch_one=True,
                )
                or 0
            )

            records = await query(
                db=self.db,
                table=DfEngineSettingLogs,
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
            )

            logs = []
            for record in serialize(records):
                record["created_at"] = format_datetime(record["created_at"])
                record["creator"] = format_user_employees(record.pop("created_by_user", None))
                record.pop("id", None)
                record.pop("created_by", None)
                previous_data = record.get("previous_data") or {}
                incoming_data = record.get("incoming_data") or {}
                record["changed_fields"] = sorted(
                    key
                    for key in (previous_data.keys() | incoming_data.keys())
                    if previous_data.get(key) != incoming_data.get(key)
                )
                logs.append(record)

            await set_json(self.redis, logs_cache_key, {"logs": logs, "total_data": total_data})
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
        summary="Get global setting.",
        description=(
            "Shows the current DF Engine settings for the whole workspace: whether the "
            "Library shows everyone's assets, the generate and enhance limits, the "
            "storyboard and prompt limits, how much of the earlier chat the assistant "
            "remembers, the limits for each project class, and which models run the "
            "enhancer and the assistant. These start from sensible defaults, so the "
            "settings page always has something to show."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def df_engine_to_fetch_global_setting(self) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            admin_setting_global_cache_key = cache_key.setting_global()
            cached_admin_setting_global = await get_json(self.redis, admin_setting_global_cache_key)
            if cached_admin_setting_global:
                logging.info(f"user={self.user['user_id']} fetched admin global setting source=cache")
                response.data = cached_admin_setting_global
                return response

            records = await query(
                db=self.db,
                table=DfEngineSettings,
                filters=(DfEngineSettings.code == SETTING_CODE,),  # type: ignore
            )
            settings = {row.key: (json.loads(row.value) if row.value else None) for row in records}

            await set_json(self.redis, admin_setting_global_cache_key, settings)
            logging.info(f"user={self.user['user_id']} fetched admin global setting count={len(settings)} source=db")
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
        summary="Update global setting.",
        description=(
            "Saves the workspace-wide DF Engine settings: Library visibility, the "
            "per-project-class usage limits, and which models power the prompt enhancer "
            "and the assistant. Send the whole settings document — this replaces the "
            "saved settings, it is not a partial update. Any change is recorded in the "
            "history together with who made it."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def df_engine_to_update_global_setting(
        self,
        schema: AdminGlobalSettingPayload,
        request: Request,
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            resolved_model: dict[str, Optional[str]] = {"enhancer_model": None, "assistant_model": None}
            for field in ("enhancer_model", "assistant_model"):
                model_uid = getattr(schema, field)
                if model_uid is None:
                    continue
                model = await query(
                    db=self.db,
                    table=DfEngineModelOptions,
                    filters=(DfEngineModelOptions.uid == str(model_uid),),  # type: ignore
                    fetch_one=True,
                )
                if model is None:
                    raise DataNotFoundError(message="model_option_not_found")
                if model.type != ModelUsageTypes.text:
                    raise DataValidationError(message="setting_engine_model_must_be_text")
                if not model.is_enabled:
                    raise DataValidationError(message="setting_engine_model_must_be_enabled")
                if not model.is_available:
                    raise DataValidationError(message="setting_engine_model_must_be_available")
                resolved_model[field] = model.name

            project_classes = await query(db=self.db, table=ProjectClasses)  # type: ignore
            class_by_id = {pc.id: pc for pc in project_classes}
            unknown_class_fields = {
                f"project_class_limitations.{index}.id": ["project_class_not_found"]
                for index, pcl in enumerate(schema.project_class_limitations)
                if pcl.id not in class_by_id
            }
            if unknown_class_fields:
                raise DataNotFoundError(message="project_class_not_found", error=unknown_class_fields)

            records = await query(
                db=self.db,
                table=DfEngineSettings,
                filters=(DfEngineSettings.code == SETTING_CODE,),  # type: ignore
            )
            rows_by_key = {row.key: row for row in records}

            saved_row = rows_by_key.get("project_class_limitations")
            saved_limits = {
                item["id"]: item
                for item in (json.loads(saved_row.value) if saved_row and saved_row.value else [])
                if isinstance(item, dict) and "id" in item
            }
            requested_limits = {pcl.id: pcl.model_dump(mode="json") for pcl in schema.project_class_limitations}

            incoming = {
                "admin_view": schema.admin_view.model_dump(mode="json"),
                "enhancer_model": resolved_model["enhancer_model"],
                "assistant_model": resolved_model["assistant_model"],
                "project_class_limitations": [
                    {
                        **(saved_limits.get(pc.id) or ProjectClassLimitations(id=pc.id).model_dump(mode="json")),
                        **requested_limits.get(pc.id, {}),
                        "id": pc.id,
                        "name": pc.name,
                        "color": pc.color,
                    }
                    for pc in project_classes
                ],
            }

            previous = {
                key: (json.loads(row.value) if row.value else None)
                for key, row in rows_by_key.items()
                if key in incoming
            }

            now = local_time()
            for key, value in incoming.items():
                serialized = json.dumps(value)
                row = rows_by_key.get(key)
                if row is None:
                    self.db.add(DfEngineSettings(code=SETTING_CODE, key=key, value=serialized, created_at=now))
                elif row.value != serialized:
                    row.value = serialized
                    row.updated_at = now
                    self.db.add(row)

            changed = bool(rows_by_key) and previous != incoming
            if changed:
                user_row = await query(
                    db=self.db,
                    table=Users,
                    filters=(Users.id == int(self.user["user_id"]),),  # type: ignore
                    fetch_one=True,
                )
                self.db.add(
                    DfEngineSettingLogs(
                        created_by=int(self.user["user_id"]),
                        user_email=user_row.email if user_row else None,
                        user_name=user_row.username if user_row else None,
                        previous_data=previous or None,
                        incoming_data=incoming,
                        ip_address=(
                            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                            or (request.client.host if request.client else None)
                        ),
                        user_agent=request.headers.get("User-Agent"),
                    )
                )
                await delete_pattern(self.redis, cache_key.setting_logs_pattern())
                await delete_pattern(self.redis, cache_key.setting_project_pattern())

            await self.db.flush()
            await delete_pattern(self.redis, cache_key.setting_global())
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
            "Returns the effective generation limits for one project. If the project has "
            "its own saved limits, those are used; otherwise they fall back to the global "
            "settings for the project's class. The global settings must have been "
            "configured at least once."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def df_engine_with_uid_to_fetch_project_setting(
        self, uid: UUID = Path(..., description="Project UID.")
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        limit_fields = (
            "token_usage_limit",
            "concurent_generations",
            "compose_input_max_chars",
            "storyboard_prompt_chars",
            "max_scene_per_storyboard",
            "max_shot_per_scene",
        )
        try:
            project_setting_cache_key = cache_key.setting_project(uid)
            cached_project_setting = await get_json(self.redis, project_setting_cache_key)
            if cached_project_setting:
                logging.info(f"user={self.user['user_id']} fetched project setting uid={uid} source=cache")
                response.data = cached_project_setting
                return response

            project = await query(
                db=self.db,
                table=Projects,
                filters=(Projects.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if not project:
                raise DataNotFoundError(message="project_not_found")

            saved = await query(
                db=self.db,
                table=DfEngineProjectSettings,
                filters=(DfEngineProjectSettings.project_id == project.id,),  # type: ignore
                fetch_one=True,
            )
            if saved:
                limits = {field: getattr(saved, field) for field in limit_fields}
                source = "project"
            else:
                row = await query(
                    db=self.db,
                    table=DfEngineSettings,
                    filters=(
                        DfEngineSettings.code == SETTING_CODE,  # type: ignore
                        DfEngineSettings.key == "project_class_limitations",  # type: ignore
                    ),
                    fetch_one=True,
                )
                if not row or not row.value:
                    raise DataValidationError(message="global_setting_not_configured")
                if project.project_class_id is None:
                    raise DataValidationError(message="project_class_not_assigned")
                class_limit = next(
                    (item for item in json.loads(row.value) if item.get("id") == project.project_class_id),
                    None,
                )
                if not class_limit:
                    raise DataNotFoundError(message="project_class_limitation_not_found")
                limits = {field: class_limit.get(field) for field in limit_fields}
                source = "project_class_default"

            data = {"project": project.name, "classification": project.classification, **limits}
            await set_json(self.redis, project_setting_cache_key, data)
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
        summary="Save project setting.",
        description=(
            "Saves a per-project override of the generation limits. Send all six limit "
            "fields — they replace whatever this project had before. While the override "
            "exists the project uses these values instead of its class limits from the "
            "global settings."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def df_engine_with_uid_to_save_project_setting(
        self,
        schema: ProjectSettingPayload,
        uid: UUID = Path(..., description="Project UID."),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            project = await query(
                db=self.db,
                table=Projects,
                filters=(Projects.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if not project:
                raise DataNotFoundError(message="project_not_found")

            user_id = int(self.user["user_id"])
            values = schema.model_dump()

            row = await query(
                db=self.db,
                table=DfEngineProjectSettings,
                filters=(DfEngineProjectSettings.project_id == project.id,),  # type: ignore
                fetch_one=True,
            )
            if row is None:
                row = DfEngineProjectSettings(project_id=project.id, created_by=user_id, **values)
            else:
                for field, value in values.items():
                    setattr(row, field, value)
                row.updated_by = user_id
            self.db.add(row)
            await self.db.flush()

            await delete_pattern(self.redis, cache_key.setting_project(uid))
            logging.info(f"user={self.user['user_id']} saved project setting uid={uid}")

            response.data = {"project": project.name, "classification": project.classification, **values}
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
