import json
import traceback
from uuid import UUID
from typing import Any, Optional
from fastapi import status, Query, Request
from fastapi_controller import controller
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import PaginationResponse, Response
from schemas.payload.setting import AdminSettingPayload
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
    async def fetch_setting_df_engine_logs(
        self,
        search: Optional[str] = Query(None, description="Filter by the saver's name (prefix match)."),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            logs_cache_key = cache_key.setting_pagination(page, itemsPerPage, search)
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
        summary="Get the DF Engine settings.",
        description=(
            "Returns the DF Engine configuration: the workspace-wide admin settings "
            "(whether the Library shows every user's assets, the per-minute "
            "generate/enhance caps, the storyboard and compose limits, how many earlier "
            "chat messages the assistant sees, and which model powers the enhancer and "
            "the assistant — returned by name, not UID). `project_class_limits` always "
            "lists every current project class (classes with no saved limit come back at "
            "0). `project_limit_override` is null unless `project_uid` is passed as a "
            "query param *and* that project has a saved override — otherwise it stays "
            "null. An unknown `project_uid` is rejected. Nothing needs to be saved first "
            "— defaults are returned so the settings page always has something to show."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def df_engine_to_fetch_settings(
        self,
        project_uid: Optional[UUID] = Query(
            None,
            description="Return this project's saved generation-limit override in `project_limit_override` (null if it has none). Omit for null.",
            examples=["c6f66cb0-9c62-46f4-9228-1604e26c09d9"],
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            if project_uid is not None:
                project_exists = await query(
                    db=self.db,
                    columns=(Projects.id,),  # type: ignore
                    table=Projects,
                    filters=(Projects.uid == str(project_uid),),  # type: ignore
                    fetch_one=True,
                )
                if not project_exists:
                    raise DataNotFoundError(message="project_not_found")

            admin_setting_cache_key = cache_key.setting_detail(project_uid)
            cached_admin_setting = await get_json(self.redis, admin_setting_cache_key)
            if cached_admin_setting:
                logging.info(
                    f"user={self.user['user_id']} fetched admin setting project_uid={project_uid} source=cache"
                )
                response.data = cached_admin_setting
                return response

            records = await query(
                db=self.db,
                table=DfEngineSettings,
                filters=(DfEngineSettings.code == SETTING_CODE,),  # type: ignore
            )

            document = AdminSettingPayload().model_dump(mode="json")
            if records:
                for record in serialize(records):
                    document[record["key"]] = json.loads(record["value"]) if record["value"] else None
                source = "database"
            else:
                source = "default (nothing saved yet)"

            stored_class_limit = {
                item["project_class_name"]: item["limit"]
                for item in document.get("project_class_limits") or []
                if "project_class_name" in item
            }
            class_names = await query(db=self.db, columns=(ProjectClasses.name,), table=ProjectClasses)  # type: ignore
            document["project_class_limits"] = [
                {"project_class_name": name, "limit": stored_class_limit.get(name, 0)} for name in class_names
            ]

            override = None
            if project_uid is not None:
                for item in document.get("project_limit_override") or []:
                    if item.get("project_uid") == str(project_uid):
                        override = {"project_name": item.get("project_name"), "limit": item.get("limit")}
                        break
            document["project_limit_override"] = override

            formatted_records = document
            await set_json(self.redis, admin_setting_cache_key, formatted_records)
            logging.info(f"user={self.user['user_id']} fetched admin setting project_uid={project_uid} source={source}")
            response.data = formatted_records
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not fetch admin setting project_uid={project_uid}: "
                f"{e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error fetching admin setting project_uid={project_uid}\n"
                f"{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.post(
        "/setting",
        summary="Save the DF Engine settings.",
        description=(
            "Saves the full settings document — this is a complete replace, not a "
            "partial diff. The workspace-wide admin settings and the per-project-class "
            "limits are stored as submitted. `project_limit_override` is optional: send "
            "`{project_uid, limit}` to upsert one project's generation cap (an unknown "
            "`project_uid` is rejected), or omit it to leave every existing per-project "
            "override untouched. `enhancer_model` / `assistant_model`, when set, must "
            "each be the UID of a currently enabled, available text model, and are "
            "stored and returned by name. A `project_class_id` that no longer exists is "
            "rejected. Every save that actually changes something is recorded to the "
            "history (see `GET /setting/logs`) along with who made it — an unchanged "
            "save and the very first save are not logged. Returns the settings as they "
            "now stand, with `project_limit_override` set to the entry that was upserted "
            "(or null when none was sent)."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def df_engine_to_post_or_update_setting(
        self,
        schema: AdminSettingPayload,
        request: Request,
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        changed = False
        incoming = schema.model_dump(mode="json")
        resolved_models: dict[str, Any] = {"enhancer_model": None, "assistant_model": None}
        try:
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
                resolved_models[field] = model.name

            incoming = {**incoming, **resolved_models}

            requested_class_limits = {pcl.project_class_id: pcl.limit for pcl in schema.project_class_limits}
            project_classes = await query(
                db=self.db,
                columns=(
                    ProjectClasses.id,
                    ProjectClasses.name,
                ),  # type: ignore
                table=ProjectClasses,
            )
            known_class_ids = {project_class.id for project_class in project_classes}
            unknown_class_fields = {
                f"project_class_limits.{index}.project_class_id": ["project_class_not_found"]
                for index, pcl in enumerate(schema.project_class_limits)
                if pcl.project_class_id not in known_class_ids
            }
            if unknown_class_fields:
                raise DataNotFoundError(message="project_class_not_found", error=unknown_class_fields)

            entry = None
            if schema.project_limit_override is not None:
                project = await query(
                    db=self.db,
                    table=Projects,
                    filters=(Projects.uid == str(schema.project_limit_override.project_uid),),  # type: ignore
                    fetch_one=True,
                )
                if not project:
                    raise DataNotFoundError(message="project_not_found")
                entry = {
                    "project_uid": str(project.uid),
                    "project_name": project.name,
                    "limit": schema.project_limit_override.limit,
                }

            records = await query(
                db=self.db,
                table=DfEngineSettings,
                filters=(DfEngineSettings.code == SETTING_CODE,),  # type: ignore
            )
            rows_by_key = {row.key: row for row in records}
            previous_doc = {key: json.loads(row.value) if row.value else None for key, row in rows_by_key.items()}

            project_limit_override = [dict(existing) for existing in (previous_doc.get("project_limit_override") or [])]
            if entry is not None:
                for index, existing in enumerate(project_limit_override):
                    if existing.get("project_uid") == entry["project_uid"]:
                        project_limit_override[index] = entry
                        break
                else:
                    project_limit_override.append(entry)

            incoming = {
                **incoming,
                "project_limit_override": project_limit_override,
                "project_class_limits": [
                    {"project_class_name": project_class.name, "limit": requested_class_limits.get(project_class.id, 0)}
                    for project_class in project_classes
                ],
            }

            previous = {key: previous_doc.get(key) for key in incoming}

            for key, value in incoming.items():
                serialized = json.dumps(value)
                row = rows_by_key.get(key)
                if row is None:
                    self.db.add(DfEngineSettings(code=SETTING_CODE, key=key, value=serialized))
                else:
                    row.value = serialized
                    row.updated_at = local_time()

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
                        user_email=user_row.email,
                        user_name=user_row.username,
                        previous_data=previous,
                        incoming_data=incoming,
                        ip_address=(
                            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                            or (request.client.host if request.client else None)
                        ),
                        user_agent=request.headers.get("User-Agent"),
                    )
                )
                await delete_pattern(self.redis, cache_key.setting_pagination_pattern())

            await self.db.flush()
            await delete_pattern(self.redis, cache_key.setting_detail_pattern())
            logging.info(f"user={self.user['user_id']} saved admin setting changed={changed}")

            response.data = {
                **incoming,
                "project_limit_override": (
                    {"project_name": entry["project_name"], "limit": entry["limit"]} if entry else None
                ),
            }
        except BaseError as e:
            logging.warning(f"user={self.user['user_id']} could not save admin setting: {e.message} ({e.status_code})")
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error saving admin setting\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response
