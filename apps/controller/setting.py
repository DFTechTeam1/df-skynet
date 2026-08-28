import json
import traceback
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
from services.mysql.model import DfEngineSettings, DfEngineSettingLogs, DfEngineModelOptions, Users, Employees
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.redis import get_json, set_json, delete_pattern, CacheKeys


class SettingController(CoreDependencies):
    @controller.get(
        "/setting",
        summary="Get the DF Engine admin settings.",
        description=(
            "Returns the admin configuration for the DF Engine workspace: whether the "
            "asset library shows every user's assets or just each user's own, the "
            "generate/enhance rate limits, the daily spend ceilings, the maximum prompt "
            "length, the storyboard limits (script length per scene, scenes per "
            "storyboard, shots per scene), how many earlier chat messages the assistant "
            "gets as context, and which model currently powers the prompt "
            "enhancer and the assistant (returned with the model's full info, not just "
            "its UID, so the page can show what it actually is). Nothing needs to be "
            "saved first — if no settings have been saved yet, the default values are "
            "returned instead of an error, so the settings page always has something "
            "to show."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def fetch_setting_df_engine(self) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            admin_setting_cache_key = cache_key.setting_detail("admin_setting")
            cached_admin_setting = await get_json(self.redis, admin_setting_cache_key)
            if cached_admin_setting:
                logging.info(f"user={self.user['user_id']} fetched admin setting source=cache")
                response.data = cached_admin_setting
                return response

            records = await query(
                db=self.db,
                table=DfEngineSettings,
                filters=(DfEngineSettings.code == "admin_setting",),  # type: ignore
            )
            if records:
                records = serialize(records)
                formatted_records = {}
                for record in records:
                    record["value"] = json.loads(record["value"]) if record["value"] else None
                    formatted_records[record["key"]] = record["value"]
                logging.info(
                    f"user={self.user['user_id']} fetched admin setting source=db keys={sorted(formatted_records)}"
                )
            else:
                formatted_records = AdminSettingPayload().model_dump(mode="json")
                logging.info(f"user={self.user['user_id']} fetched admin setting source=default")

            await set_json(self.redis, admin_setting_cache_key, formatted_records)
            response.data = formatted_records
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/setting",
        summary="Save the DF Engine admin settings.",
        description=(
            "Saves the full admin configuration in one call — the same endpoint is used "
            "for the very first save and every save after that, so the settings page "
            "never needs to know whether settings already exist yet. The request must "
            "include every field; `enhancer_model` and `assistant_model` are optional — "
            "when set, each must be the UID of a model that is currently an enabled, "
            "available text model, and left blank falls back to the engine's built-in "
            "default. "
            "Once settings exist, every save that actually changes something is "
            "recorded to the settings history (see `GET /setting/logs`) along with "
            "who made the change; a save that doesn't change anything isn't logged, "
            "and neither is the very first save (it just inserts the rows — there's "
            "no prior state to diff against). `enhancer_model` / `assistant_model` "
            "are stored and returned as the model name, not the UID. Returns the "
            "settings as they now stand."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def create_setting_df_engine(self, schema: AdminSettingPayload, request: Request) -> Response:
        response = Response()
        cache_key = CacheKeys()
        SETTING_CODE = "admin_setting"
        try:
            incoming = schema.model_dump(mode="json")
            resolved_models: dict[str, Any] = {"enhancer_model": None, "assistant_model": None}

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
            changed = False

            records = await query(
                db=self.db,
                table=DfEngineSettings,
                filters=(DfEngineSettings.code == SETTING_CODE,),  # type: ignore
            )

            if records:
                rows_by_key = {row.key: row for row in records}
                previous = {key: json.loads(row.value) if row.value else None for key, row in rows_by_key.items()}

                for key, value in incoming.items():
                    serialized = json.dumps(value)
                    row = rows_by_key.get(key)

                    if row is None:
                        self.db.add(DfEngineSettings(code=SETTING_CODE, key=key, value=serialized))
                    else:
                        row.value = serialized
                        row.updated_at = local_time()

                changed = previous != incoming
                if changed:
                    user_data = await query(
                        db=self.db,
                        table=Users,
                        filters=(Users.id == self.user["user_id"],),  # type: ignore
                        fetch_one=True,
                    )
                    self.db.add(
                        DfEngineSettingLogs(
                            created_by=self.user["user_id"],
                            user_email=user_data.email if user_data and user_data.email else None,
                            user_name=user_data.username if user_data and user_data.username else None,
                            previous_data=previous,
                            incoming_data=incoming,
                            ip_address=(
                                request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                                or (request.client.host if request.client else None)
                            ),
                            user_agent=request.headers.get("User-Agent"),
                        )
                    )

                logging.info(f"user={self.user['user_id']} updated admin setting changed={changed}")
                await delete_pattern(self.redis, cache_key.setting_pagination_pattern())
            else:
                for key, value in incoming.items():
                    self.db.add(DfEngineSettings(code=SETTING_CODE, key=key, value=json.dumps(value)))
                logging.info(f"user={self.user['user_id']} created admin setting")

            await self.db.flush()
            await set_json(self.redis, cache_key.setting_detail(SETTING_CODE), incoming)
            response.data = incoming
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/setting/logs",
        summary="View the history of changes made to the DF Engine admin settings.",
        description=(
            "Returns the settings audit trail, newest first: every time the admin "
            "settings were saved with an actual change, this lists who saved it "
            "(`creator`) and the settings as they were right before that save "
            "(`previous_data`) next to what they became (`incoming_data`), so any "
            "change can be traced back to who made it and exactly what moved. "
            "`previous_data` is null for the very first save, since there's nothing "
            "to compare it against. A save that didn't change anything isn't recorded "
            "here. Paginated — pass `page` and `itemsPerPage` to page through history."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def fetch_setting_df_engine_logs(
        self,
        search: Optional[str] = Query(None, description="search by username prefix matched"),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            logs_cache_key = cache_key.setting_pagination(page, itemsPerPage, search)
            cached = await get_json(self.redis, logs_cache_key)
            if cached is not None:
                logging.info(f"user={self.user['user_id']} listed setting logs source=cache key={logs_cache_key}")
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
                logs.append(record)

            logging.info(
                f"user={self.user['user_id']} listed setting logs search={search!r} "
                f"page={page} size={itemsPerPage} count={len(logs)} total={total_data}"
            )
            await set_json(self.redis, logs_cache_key, {"logs": logs, "total_data": total_data})
            response.data = PaginationResponse(paginated=logs, totalData=total_data)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
