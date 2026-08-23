import traceback
from datetime import date
from typing import Any, Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import func, update
from apps.controller.core import CoreDependencies
from schemas.payload.model_management import SetModelEnabledPayload
from schemas.response import PaginationResponse, Response
from services.mysql.model import DfEngineModelOptions
from log import logging
from error import ServiceError, BaseError, DataNotFoundError, DataValidationError
from utils import epoch_to_wib, local_time
from utils.formatter import format_datetime
from utils.serializer import serialize
from enum import StrEnum, auto
from services.openrouter import call_openrouter
from services.mysql import query


class ModelUsageTypes(StrEnum):
    text = auto()
    image = auto()
    video = auto()


model_management_permission = {
    "fetch_df_engine_model_option": "fetch_df_engine_model_option",
    "sync_df_engine_option": "sync_df_engine_option",
}


class ModelManagementController(CoreDependencies):
    def parse_model_date(self, value: Any) -> Optional[date]:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    def format_response(self, record: dict[str, Any], has_sync_permission: bool) -> dict[str, Any]:
        record["last_sync_at"] = format_datetime(record["last_sync_at"])
        record["created"] = format_datetime(epoch_to_wib(record["created"]))
        record["action"] = {
            "can_set_enabled": has_sync_permission and record["is_available"],
            "can_set_main": has_sync_permission
            and record["is_available"]
            and record["is_enabled"]
            and not record["is_main"],
        }

        record.pop("id", None)
        return record

    async def get_model_option(self, uid: UUID) -> DfEngineModelOptions:
        record = await query(
            db=self.db,
            table=DfEngineModelOptions,
            filters=(DfEngineModelOptions.uid == str(uid),),  # type: ignore
            fetch_one=True,
        )
        if record is None:
            raise DataNotFoundError(message="model_option_not_found")
        return record

    def model_option_fields(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": item.get("name") or item.get("id"),
            "created": item.get("created"),
            "description": item.get("description"),
            "architecture": item.get("architecture"),
            "supported_parameters": item.get("supported_parameters"),
            "default_parameters": item.get("default_parameters"),
            "supports_streaming": item.get("supports_streaming"),
            "supported_resolutions": item.get("supported_resolutions"),
            "supported_aspect_ratios": item.get("supported_aspect_ratios"),
            "supported_sizes": item.get("supported_sizes"),
            "supported_durations": item.get("supported_durations"),
            "supported_frame_images": item.get("supported_frame_images"),
            "generate_audio": item.get("generate_audio"),
            "allowed_passthrough_parameters": item.get("allowed_passthrough_parameters"),
            "pricing_skus": item.get("pricing_skus"),
            "pricing": item.get("pricing"),
            "top_provider": item.get("top_provider"),
            "knowledge_cutoff": self.parse_model_date(item.get("knowledge_cutoff")),
            "expiration_date": self.parse_model_date(item.get("expiration_date")),
        }

    async def sync_model_type(self, model_type: str, items: list[dict[str, Any]]) -> dict[str, int]:
        """1:1 sync of `items` (OpenRouter's model list for `model_type`) onto
        df_engine_model_options: models we don't have yet are inserted, models we
        already have are refreshed and marked available, and models we have locally
        but OpenRouter no longer returned are flagged `is_available = False` rather
        than deleted, so `is_main` / `is_enabled` history isn't lost.
        """
        existing_rows = await query(
            db=self.db,
            table=DfEngineModelOptions,
            filters=(DfEngineModelOptions.type == model_type,),
        )
        existing_by_model_id = {row.model_id: row for row in existing_rows}
        fetched_model_ids: set[str] = set()
        inserted = updated = disabled = skipped = 0

        for item in items:
            model_id = item.get("id")
            if not model_id:
                skipped += 1
                continue
            fetched_model_ids.add(model_id)
            fields = self.model_option_fields(item)

            row = existing_by_model_id.get(model_id)
            if row is None:
                self.db.add(
                    DfEngineModelOptions(
                        model_id=model_id,
                        type=model_type,  # type: ignore
                        is_available=True,
                        last_sync_at=local_time(),
                        **fields,
                    )
                )
                inserted += 1
            else:
                for key, value in fields.items():
                    setattr(row, key, value)
                row.is_available = True
                row.last_sync_at = local_time()
                updated += 1

        for model_id, row in existing_by_model_id.items():
            if model_id not in fetched_model_ids and row.is_available:
                row.is_available = False
                disabled += 1

        if skipped:
            logging.warning(
                f"user={self.user['user_id']} model sync type={model_type}: skipped {skipped} item(s) missing an 'id'"
            )

        return {"inserted": inserted, "updated": updated, "disabled": disabled, "skipped": skipped}

    @controller.get(
        "/models",
        summary="List models synced from OpenRouter.",
        description=(
            "Returns `df_engine_model_options` rows still available on OpenRouter "
            "(`is_available = true`), paginated and ordered by type then name. Models "
            "the sync endpoint has flagged unavailable are excluded. Pass `type` to "
            "restrict results to one usage type, `search` to filter by name "
            "(case-insensitive, prefix match), and/or `is_enabled` to view only "
            "enabled or only disabled models — e.g. list enabled models as the pool "
            "to pick a new main from, without a separate endpoint."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_fetch_available_models(
        self,
        type: Optional[ModelUsageTypes] = Query(
            default=None,
            description="Restrict results to one usage type. Omit to include all types.",
        ),
        search: Optional[str] = Query(
            default=None,
            min_length=1,
            description="Search text to filter models by name (case-insensitive, prefix match). Omit to list all.",
            examples=["gemini"],
        ),
        is_enabled: Optional[bool] = Query(
            default=None,
            description="Filter by enabled state. Omit to include both enabled and disabled models.",
        ),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=500, ge=1, le=500, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        try:
            filters: list[Any] = [DfEngineModelOptions.is_available.is_(True)]  # type: ignore
            if type:
                filters.append(DfEngineModelOptions.type == type)  # type: ignore
            if search:
                filters.append(DfEngineModelOptions.name.ilike(f"{search}%"))  # type: ignore
            if is_enabled is not None:
                filters.append(DfEngineModelOptions.is_enabled.is_(is_enabled))  # type: ignore
            query_filters = tuple(filters)

            total_data = await query(
                db=self.db,
                table=DfEngineModelOptions,
                columns=(func.count(DfEngineModelOptions.id),),  # type: ignore
                filters=query_filters,
                fetch_one=True,
            )

            records = await query(
                db=self.db,
                table=DfEngineModelOptions,
                filters=query_filters,
                order_by=(DfEngineModelOptions.type.asc(), DfEngineModelOptions.name.asc()),  # type: ignore
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
            )

            # has_sync_permission = model_management_permission["sync_df_engine_option"] in self.user.get(
            #     "permissions", []
            # )
            has_sync_permission = True  # will be overide first

            response.data = PaginationResponse(
                paginated=[self.format_response(record, has_sync_permission) for record in serialize(records)],
                totalData=total_data or 0,
            )
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/models/{uid}",
        summary="Enable or disable a model.",
        description=(
            "Toggles whether a model is enabled (selectable in the product). Requires "
            "the model to still be available on OpenRouter (`is_available = true`) — "
            "a model OpenRouter no longer returns can't be enabled or disabled through "
            "this endpoint either way. Only an enabled model can be set as main — "
            "disabling a model that currently holds `is_main` also clears that flag, "
            "since a disabled model can never stay main. Returns the updated model."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_set_model_enabled(
        self,
        schema: SetModelEnabledPayload,
        uid: UUID = Path(
            ...,
            description="Model UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            record = await self.get_model_option(uid)
            if not record.is_available:
                raise DataValidationError(message="model_option_unavailable_cannot_set_enabled")

            record.is_enabled = schema.is_enabled
            if not schema.is_enabled and record.is_main:
                record.is_main = False

            await self.db.flush()
            logging.info(
                f"user={self.user['user_id']} model uid={record.uid} model_id={record.model_id} "
                f"is_enabled={record.is_enabled} is_main={record.is_main}"
            )

            # has_sync_permission = model_management_permission["sync_df_engine_option"] in self.user.get(
            #     "permissions", []
            # )
            has_sync_permission = True  # will be overide first
            response.data = self.format_response(serialize(record), has_sync_permission)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/models/{uid}/main",
        summary="Set a model as the main model for its type.",
        description=(
            "Marks this model as the main one for its usage type (`text`, `image`, "
            "`video`) — the model must be available on OpenRouter and already enabled. "
            "At most one model per type can be main at a time, so this overrides "
            "whichever model currently holds it: the previous main model for the same "
            "type is cleared automatically, no separate confirmation needed. Returns "
            "the updated model."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_set_model_main(
        self,
        uid: UUID = Path(
            ...,
            description="Model UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            record = await self.get_model_option(uid)
            if not record.is_available:
                raise DataValidationError(message="model_option_unavailable_cannot_set_main")
            if not record.is_enabled:
                raise DataValidationError(message="model_option_must_be_enabled_to_set_main")

            if not record.is_main:
                await self.db.execute(
                    update(DfEngineModelOptions)
                    .where(
                        DfEngineModelOptions.type == record.type,  # type: ignore
                        DfEngineModelOptions.id != record.id,  # type: ignore
                        DfEngineModelOptions.is_main.is_(True),  # type: ignore
                    )
                    .values(is_main=False)
                )
                record.is_main = True
                await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} model uid={record.uid} model_id={record.model_id} "
                f"set as main type={record.type}"
            )

            # has_sync_permission = model_management_permission["sync_df_engine_option"] in self.user.get(
            #     "permissions", []
            # )
            has_sync_permission = True  # will be overide first
            response.data = self.format_response(serialize(record), has_sync_permission)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/models",
        summary="Sync models from OpenRouter.",
        description=(
            "Fetches OpenRouter's current model list for each usage type (`text`, "
            "`image`, `video`) and reconciles it 1:1 against `df_engine_model_options`: "
            "models not seen before are inserted, models already on file are refreshed "
            "and marked available, and models on file that OpenRouter no longer returns "
            "are flagged `is_available = false` rather than deleted, so `is_main` / "
            "`is_enabled` history is preserved. Every OpenRouter call — success or "
            "failure — is recorded in the audit log."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_sync_available_models(self) -> Response:
        response = Response()
        endpoints = {
            "text": "/models?output_modalities=text",
            "video": "/videos/models",
            "image": "/videos/models",
        }
        totals = {"inserted": 0, "updated": 0, "disabled": 0, "skipped": 0}
        try:
            for model_type, path in endpoints.items():
                openrouter_response = await call_openrouter(
                    db=self.db,
                    user_id=int(self.user["user_id"]),
                    method="GET",
                    path=path,
                )

                if isinstance(openrouter_response, dict) and "data" in openrouter_response:
                    items = openrouter_response.get("data")
                elif isinstance(openrouter_response, list):
                    items = openrouter_response
                else:
                    items = None

                if items is None:
                    # An error payload (e.g. {"error": ...}) has no "data" key — treating
                    # that as "zero models" would flag every existing model of this type
                    # unavailable, so skip syncing this type instead of trusting it.
                    logging.warning(
                        f"user={self.user['user_id']} model sync skipped type={model_type} path={path}: "
                        f"unexpected OpenRouter response shape response={openrouter_response!r}"
                    )
                    continue

                result = await self.sync_model_type(model_type, items)
                for key in totals:
                    totals[key] += result[key]
                logging.info(
                    f"user={self.user['user_id']} model sync type={model_type} "
                    f"inserted={result['inserted']} updated={result['updated']} "
                    f"disabled={result['disabled']} skipped={result['skipped']}"
                )

            await self.db.flush()
            logging.info(
                f"user={self.user['user_id']} model sync summary: "
                f"inserted={totals['inserted']} updated={totals['updated']} "
                f"disabled={totals['disabled']} skipped={totals['skipped']}"
            )
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
