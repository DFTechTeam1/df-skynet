import json
import traceback
from typing import Any, Optional
from uuid import UUID
from fastapi import status, Query, Request
from fastapi_controller import controller
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import PaginationResponse, Response
from schemas.payload.setting import (
    AdminSettingPayload,
    AdminView,
    UserRateLimit,
    UserSpendCeiling,
    UserStoryboard,
    UserComposeInput,
    ChatAssistant,
)
from log import logging
from error import ServiceError, BaseError, DataNotFoundError, DataValidationError
from utils import local_time
from utils.formatter import format_datetime, format_user_employees
from utils.serializer import serialize
from services.mysql import query
from services.mysql.model import DfEngineSettings, DfEngineSettingLogs, DfEngineModelOptions, Users, Employees
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.redis import get_json, set_json, delete_pattern

SETTING_CODE = "admin_setting"

CACHE_TTL_SECONDS = 3600
DETAIL_CACHE_KEY = f"setting:detail:{SETTING_CODE}"
LOGS_CACHE_PATTERN = "setting:logs:*"


def logs_cache_key(page: int, items_per_page: int) -> str:
    return f"setting:logs:page={page}:size={items_per_page}"


class SettingController(CoreDependencies):
    async def get_setting_rows(self) -> dict[str, DfEngineSettings]:
        rows = await query(
            db=self.db,
            table=DfEngineSettings,
            filters=(DfEngineSettings.code == SETTING_CODE,),  # type: ignore
        )
        return {row.key: row for row in rows}

    def _parse_group(self, rows: dict[str, DfEngineSettings], key: str, model_cls: type) -> dict[str, Any]:
        row = rows.get(key)
        if row and row.value:
            return json.loads(row.value)
        return model_cls().model_dump(mode="json")

    def _raw_snapshot(self, rows: dict[str, DfEngineSettings]) -> dict[str, Any]:
        """The stored settings shaped exactly like `AdminSettingPayload` (plain
        `enhancer_model`/`assistant_model` UIDs, not resolved model info) — this is
        what changes get diffed against, so an unrelated model-catalog change (e.g.
        a re-sync updating a model's name) never gets mistaken for a settings edit.
        """
        enhancer_row = rows.get("enhancer_model")
        assistant_row = rows.get("assistant_model")
        return {
            "admin_view": self._parse_group(rows, "admin_view", AdminView),
            "limit": self._parse_group(rows, "limit", UserRateLimit),
            "spend_ceiling": self._parse_group(rows, "spend_ceiling", UserSpendCeiling),
            "storyboard": self._parse_group(rows, "storyboard", UserStoryboard),
            "compose_input": self._parse_group(rows, "compose_input", UserComposeInput),
            "chat_assistant": self._parse_group(rows, "chat_assistant", ChatAssistant),
            "enhancer_model": enhancer_row.value if enhancer_row and enhancer_row.value else None,
            "assistant_model": assistant_row.value if assistant_row and assistant_row.value else None,
        }

    async def resolve_engine_model(self, uid: Optional[str]) -> Optional[DfEngineModelOptions]:
        """Look up the full model info behind a saved `enhancer_model`/`assistant_model`
        UID, so the settings page can show what the model actually is, not just its UID.
        """
        if not uid:
            return None

        return await query(
            db=self.db,
            table=DfEngineModelOptions,
            filters=(DfEngineModelOptions.uid == uid,),  # type: ignore
            fetch_one=True,
        )

    async def validate_engine_model(self, uid: Optional[UUID]) -> Optional[DfEngineModelOptions]:
        """`enhancer_model`/`assistant_model` may only reference a model that's
        currently an enabled, available text model — the same pool the settings
        page's Enhancer/Assistant dropdowns are allowed to pick from.
        """
        if uid is None:
            return None

        record = await query(
            db=self.db,
            table=DfEngineModelOptions,
            filters=(DfEngineModelOptions.uid == str(uid),),  # type: ignore
            fetch_one=True,
        )
        if record is None:
            raise DataNotFoundError(message="model_option_not_found")
        if record.type != ModelUsageTypes.text:
            raise DataValidationError(message="setting_engine_model_must_be_text")
        if not record.is_enabled:
            raise DataValidationError(message="setting_engine_model_must_be_enabled")
        if not record.is_available:
            raise DataValidationError(message="setting_engine_model_must_be_available")
        return record

    async def build_setting_response(self) -> dict[str, Any]:
        """The settings config is global, not per-user (no `action`/permission
        block like the other controllers' list responses), so the fully
        resolved response can be cached and returned as-is — no per-request
        reformatting step is needed.
        """
        cached = await get_json(self.redis, DETAIL_CACHE_KEY)
        if cached is not None:
            return cached

        rows = await self.get_setting_rows()
        enhancer_row = rows.get("enhancer_model")
        assistant_row = rows.get("assistant_model")
        enhancer_model = await self.resolve_engine_model(enhancer_row.value if enhancer_row else None)
        assistant_model = await self.resolve_engine_model(assistant_row.value if assistant_row else None)

        result = {
            "admin_view": self._parse_group(rows, "admin_view", AdminView),
            "limit": self._parse_group(rows, "limit", UserRateLimit),
            "spend_ceiling": self._parse_group(rows, "spend_ceiling", UserSpendCeiling),
            "storyboard": self._parse_group(rows, "storyboard", UserStoryboard),
            "compose_input": self._parse_group(rows, "compose_input", UserComposeInput),
            "chat_assistant": self._parse_group(rows, "chat_assistant", ChatAssistant),
            "enhancer_model": serialize(enhancer_model) if enhancer_model else None,
            "assistant_model": serialize(assistant_model) if assistant_model else None,
        }
        await set_json(self.redis, DETAIL_CACHE_KEY, result, ttl=CACHE_TTL_SECONDS)
        return result

    def _client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0]
        return forwarded_for or (request.client.host if request.client else "127.0.0.1")

    async def _snapshot_user(self, user_id: int) -> tuple[Optional[str], Optional[str]]:
        record = await query(
            db=self.db,
            table=Users,
            options=(selectinload(Users.employees).load_only(Employees.name),),  # type: ignore
            filters=(Users.id == user_id,),  # type: ignore
            fetch_one=True,
        )
        if record is None:
            return None, None
        return record.email, record.employees.name if record.employees else None

    async def upsert_setting_rows(self, schema: AdminSettingPayload, request: Request) -> None:
        enhancer_model = await self.validate_engine_model(schema.enhancer_model)
        assistant_model = await self.validate_engine_model(schema.assistant_model)

        rows = await self.get_setting_rows()
        is_first_save = not rows
        # `None` on the very first save — there's genuinely no prior state to
        # compare against yet, so that save is still logged, just with a null
        # `previous_data`.
        previous_snapshot = None if is_first_save else self._raw_snapshot(rows)

        incoming_snapshot: dict[str, Any] = {
            "admin_view": schema.admin_view.model_dump(mode="json"),
            "limit": schema.limit.model_dump(mode="json"),
            "spend_ceiling": schema.spend_ceiling.model_dump(mode="json"),
            "storyboard": schema.storyboard.model_dump(mode="json"),
            "compose_input": schema.compose_input.model_dump(mode="json"),
            "chat_assistant": schema.chat_assistant.model_dump(mode="json"),
            "enhancer_model": enhancer_model.uid if enhancer_model else None,
            "assistant_model": assistant_model.uid if assistant_model else None,
        }

        values_by_key: dict[str, Optional[str]] = {
            "admin_view": json.dumps(incoming_snapshot["admin_view"]),
            "limit": json.dumps(incoming_snapshot["limit"]),
            "spend_ceiling": json.dumps(incoming_snapshot["spend_ceiling"]),
            "storyboard": json.dumps(incoming_snapshot["storyboard"]),
            "compose_input": json.dumps(incoming_snapshot["compose_input"]),
            "chat_assistant": json.dumps(incoming_snapshot["chat_assistant"]),
            "enhancer_model": incoming_snapshot["enhancer_model"],
            "assistant_model": incoming_snapshot["assistant_model"],
        }

        for key, value in values_by_key.items():
            row = rows.get(key)
            if row is None:
                self.db.add(DfEngineSettings(key=key, value=value, code=SETTING_CODE))
            else:
                row.value = value
                row.updated_at = local_time()

        changed = is_first_save or previous_snapshot != incoming_snapshot
        if changed:
            user_id = int(self.user["user_id"])
            user_email, user_name = await self._snapshot_user(user_id)
            self.db.add(
                DfEngineSettingLogs(
                    created_by=user_id,
                    user_email=user_email,
                    user_name=user_name,
                    previous_data=previous_snapshot,
                    incoming_data=incoming_snapshot,
                    ip_address=self._client_ip(request),
                    user_agent=request.headers.get("User-Agent"),
                )
            )

        await self.db.flush()

        logging.info(f"user={self.user['user_id']} saved settings code={SETTING_CODE} changed={changed}")

        await self.redis.delete(DETAIL_CACHE_KEY)
        if changed:
            # Only a real change adds a new df_engine_setting_logs row — an
            # unchanged save has nothing new for the logs cache to miss.
            await delete_pattern(self.redis, LOGS_CACHE_PATTERN)

    async def fetch_setting_logs(self, page: int, items_per_page: int) -> tuple[list[dict[str, Any]], int]:
        """No `action`/permission block here either (each entry's `creator` is
        who made *that* historical change, not the current caller), so the
        fully formatted page can be cached and returned as-is, keyed by page
        + page size like model_management's multi-dimension list.
        """
        cache_key = logs_cache_key(page, items_per_page)
        cached = await get_json(self.redis, cache_key)
        if cached is not None:
            return cached["logs"], cached["total_data"]

        query_options = (
            selectinload(DfEngineSettingLogs.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        )

        total_data = await query(
            db=self.db,
            table=DfEngineSettingLogs,
            columns=(func.count(DfEngineSettingLogs.id),),  # type: ignore
            fetch_one=True,
        )

        records = await query(
            db=self.db,
            table=DfEngineSettingLogs,
            options=query_options,
            order_by=(DfEngineSettingLogs.created_at.desc(), DfEngineSettingLogs.id.desc()),  # type: ignore
            limit=items_per_page,
            offset=(page - 1) * items_per_page,
        )

        logs = []
        for record in serialize(records):
            record["created_at"] = format_datetime(record["created_at"])
            record["creator"] = format_user_employees(record.pop("created_by_user", None))
            record.pop("id", None)
            record.pop("created_by", None)
            logs.append(record)

        total_data = total_data or 0
        await set_json(self.redis, cache_key, {"logs": logs, "total_data": total_data}, ttl=CACHE_TTL_SECONDS)
        return logs, total_data

    @controller.get(
        "/setting",
        summary="Get the current DF Engine admin settings.",
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
        try:
            response.data = await self.build_setting_response()
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
            "Every save that actually changes something is recorded to the settings "
            "history (see `GET /setting/logs`) along with who made the change — "
            "including the very first save, which has no prior settings to compare "
            "against; a save that doesn't change anything isn't logged. Returns the "
            "settings as they now stand."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Setting"],
        response_model=Response,
    )
    async def create_setting_df_engine(self, schema: AdminSettingPayload, request: Request) -> Response:
        response = Response()
        try:
            await self.upsert_setting_rows(schema, request)
            response.data = await self.build_setting_response()
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
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        try:
            logs, total_data = await self.fetch_setting_logs(page, itemsPerPage)
            response.data = PaginationResponse(paginated=logs, totalData=total_data)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
