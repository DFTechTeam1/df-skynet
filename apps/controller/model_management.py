import json
import time
import traceback
from typing import Optional, Literal
from uuid import UUID
from fastapi import status, Path, Query, Request
from fastapi_controller import controller
from sqlalchemy import func
from apps.controller.core import CoreDependencies
from schemas.payload.model_management import SetModelEnabledPayload
from schemas.response import PaginationResponse, Response
from services.mysql.model import DfEngineModelOptions
from services.redis import get_json, set_json, delete_pattern, CacheKeys
from log import logging
from apps.secret import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from error import ServiceError, BaseError, DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize
from services.mysql import query
from services.api_caller import APICaller
from services.model_management import ModelManagement
from services.mysql.model import Employees, DfEngineOpenrouterLogs, DfEngineSettings, DfEngineSettingLogs, Users
from utils.formatter import format_date


model_management_service = ModelManagement()


class ModelManagementController(CoreDependencies):
    @controller.get(
        "/models",
        summary="List models synced from OpenRouter.",
        description=(
            "Returns `df_engine_model_options` rows still available on OpenRouter "
            "(`is_available = true`) and not soft-deleted, paginated and ordered by "
            "type then name. Models the sync endpoint has flagged unavailable are "
            "excluded. Pass `type` to restrict results to one usage type, `search` to "
            "filter by name (case-insensitive, prefix match), and/or `is_enabled` to "
            "view only enabled or only disabled models. Pass `is_deleted=true` to list "
            "the soft-deleted models instead (the recovery view) — availability is "
            "ignored there. Each row's `action` block reports `can_delete` / "
            "`can_recover` alongside the enable/main flags."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_fetch_available_models(
        self,
        type: Optional[Literal["text", "video", "image"]] = Query(
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
        is_deleted: Optional[bool] = Query(
            default=None,
            description=(
                "Omit or pass false for the normal list (available, not deleted). Pass true to list only "
                "soft-deleted models — the recovery view; `is_available` is not applied there."
            ),
        ),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=500, ge=1, le=500, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            models_cache_key = cache_key.model_pagination(page, itemsPerPage, search, type, is_enabled, is_deleted)
            cached = await get_json(self.redis, models_cache_key)
            if cached is not None:
                logging.info(f"user={self.user['user_id']} listed model options source=cache key={models_cache_key}")
                response.data = PaginationResponse(paginated=cached["models"], totalData=cached["total_data"])
                return response

            filters = tuple(
                model_management_service.list_conditions(
                    is_deleted=is_deleted, type=type, search=search, is_enabled=is_enabled
                )
            )

            total_data = (
                await query(
                    db=self.db,
                    table=DfEngineModelOptions,
                    columns=(func.count(DfEngineModelOptions.id),),  # type: ignore
                    filters=filters,
                    fetch_one=True,
                )
                or 0
            )

            records = await query(
                db=self.db,
                table=DfEngineModelOptions,
                filters=filters,
                order_by=(DfEngineModelOptions.type.asc(), DfEngineModelOptions.name.asc()),  # type: ignore
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
            )

            models = [model_management_service.format(record, for_list=True) for record in serialize(records)]

            logging.info(
                f"user={self.user['user_id']} listed model options type={type!r} search={search!r} "
                f"is_enabled={is_enabled} is_deleted={is_deleted} page={page} size={itemsPerPage} "
                f"count={len(models)} total={total_data}"
            )
            await set_json(self.redis, models_cache_key, {"models": models, "total_data": total_data})
            response.data = PaginationResponse(paginated=models, totalData=total_data)
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
            "since a disabled model can never stay main. Disabling a model that's "
            "currently saved as the settings page's enhancer or assistant model also "
            "clears that reference back to blank (falls back to the engine's "
            "default) — the settings page can only keep an enabled model selected. "
            "Returns the updated model."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_set_enable_disable(
        self,
        schema: SetModelEnabledPayload,
        uid: UUID = Path(
            ...,
            description="Model UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            model = await query(
                db=self.db, table=DfEngineModelOptions, filters=(DfEngineModelOptions.uid == str(uid),), fetch_one=True
            )
            if not model:
                raise DataNotFoundError(message="model_option_not_found")

            if model.is_available is False:
                raise DataValidationError(message="model_option_unavailable_cannot_set_enabled")

            if model.is_main is True and schema.is_enabled is False:
                raise DataValidationError(message="model_option_main_cannot_be_disabled")

            model.is_enabled = schema.is_enabled
            await self.db.flush()
            logging.info(
                f"user={self.user['user_id']} model uid={model.uid} model_id={model.model_id} "
                f"is_enabled={model.is_enabled} is_main={model.is_main}"
            )

            await delete_pattern(self.redis, cache_key.model_pagination_pattern())
            response.data = model_management_service.format(serialize(model))
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.delete(
        "/models/{uid}",
        summary="Soft-delete a model.",
        description=(
            "Marks a model as deleted (`deleted_at` set to now, `deleted_by` set to the "
            "authenticated user) so it drops out of the default list. Only allowed when "
            "the model is still available on OpenRouter, is not enabled, and is not the "
            "main model — 422 otherwise. Nothing is removed from the database; recover it "
            "with `PATCH /models/{uid}/recover`. Returns the updated model."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_delete_model(
        self,
        uid: UUID = Path(..., description="Model UID.", examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"]),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            model = await query(
                db=self.db, table=DfEngineModelOptions, filters=(DfEngineModelOptions.uid == str(uid),), fetch_one=True
            )
            if not model:
                raise DataNotFoundError(message="model_option_not_found")
            if model.deleted_at is not None:
                raise DataValidationError(message="model_option_already_deleted")
            # is_main implies is_enabled (DB check constraint), so test main first
            # or its message would never surface.
            if model.is_main:
                raise DataValidationError(message="model_option_main_cannot_be_deleted")
            if model.is_enabled:
                raise DataValidationError(message="model_option_active_cannot_be_deleted")
            if model.is_available is False:
                raise DataValidationError(message="model_option_unavailable_cannot_be_deleted")

            model.deleted_at = local_time()
            model.deleted_by = int(self.user["user_id"])
            await self.db.flush()
            logging.info(f"user={self.user['user_id']} soft-deleted model uid={model.uid} model_id={model.model_id}")

            await delete_pattern(self.redis, cache_key.model_pagination_pattern())
            response.data = model_management_service.format(serialize(model))
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/models/{uid}/recover",
        summary="Recover a soft-deleted model.",
        description=(
            "Undoes a soft-delete: clears `deleted_at` and `deleted_by` so the model "
            "returns to the normal list. 422 if the model is not currently deleted. "
            "Its `is_available` is whatever the last sync left it at — run a sync to "
            "refresh it. Returns the updated model."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_recover_model(
        self,
        uid: UUID = Path(..., description="Model UID.", examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"]),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            model = await query(
                db=self.db, table=DfEngineModelOptions, filters=(DfEngineModelOptions.uid == str(uid),), fetch_one=True
            )
            if not model:
                raise DataNotFoundError(message="model_option_not_found")
            if model.deleted_at is None:
                raise DataValidationError(message="model_option_not_deleted")

            model.deleted_at = None
            model.deleted_by = None
            await self.db.flush()
            logging.info(f"user={self.user['user_id']} recovered model uid={model.uid} model_id={model.model_id}")

            await delete_pattern(self.redis, cache_key.model_pagination_pattern())
            response.data = model_management_service.format(serialize(model))
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
            "`is_enabled` history is preserved. Soft-deleted models are skipped entirely "
            "— their `is_available` is left frozen until they are recovered. Every "
            "OpenRouter call — success or "
            "failure — is recorded in the audit log."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_sync_available_models(self, request: Request) -> Response:
        response = Response()
        cache_key = CacheKeys()
        request_headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
        endpoints = {
            "text": "/models?output_modalities=text",
            "video": "/videos/models",
            "image": "/images/models",
        }
        try:
            async with APICaller(base_url=OPENROUTER_BASE_URL, headers=request_headers) as caller:
                for model_type, path in endpoints.items():
                    error_message = None
                    started_at = time.perf_counter()
                    openrouter_response = await caller.call("GET", path, raise_for_status=False)
                    response_body = openrouter_response.json() if openrouter_response.content else {}
                    response_status_code = openrouter_response.status_code
                    response_headers = dict(openrouter_response.headers)
                    endpoint = str(openrouter_response.request.url)

                    try:
                        if openrouter_response.is_error:
                            raise ServiceError(message="openrouter_model_fetch_failed")

                        openrouter_models = response_body.get("data", [])

                        saved_models = await query(
                            db=self.db,
                            table=DfEngineModelOptions,
                            filters=(DfEngineModelOptions.type == model_type,),
                        )
                        saved_by_model_id = {row.model_id: row for row in saved_models}
                        fetched_model_ids = {model["id"] for model in openrouter_models if model.get("id")}

                        for item in openrouter_models:
                            model_id = item.get("id")
                            if not model_id:
                                continue
                            row = saved_by_model_id.get(model_id) or DfEngineModelOptions(
                                model_id=model_id,
                                type=model_type,  # type: ignore
                            )
                            # A soft-deleted model stays frozen: sync neither refreshes
                            # it nor touches its is_available. Recover it to bring it back.
                            if row.deleted_at is not None:
                                continue
                            row.name = item.get("name") or model_id
                            row.created = item.get("created")
                            row.description = item.get("description")
                            row.architecture = item.get("architecture")
                            row.supported_parameters = item.get("supported_parameters")
                            row.default_parameters = item.get("default_parameters")
                            row.supports_streaming = item.get("supports_streaming")
                            row.supported_resolutions = item.get("supported_resolutions")
                            row.supported_aspect_ratios = item.get("supported_aspect_ratios")
                            row.supported_sizes = item.get("supported_sizes")
                            row.supported_durations = item.get("supported_durations")
                            row.supported_frame_images = item.get("supported_frame_images")
                            row.generate_audio = item.get("generate_audio")
                            row.allowed_passthrough_parameters = item.get("allowed_passthrough_parameters")
                            row.pricing_skus = item.get("pricing_skus")
                            row.pricing = item.get("pricing")
                            row.top_provider = item.get("top_provider")
                            row.knowledge_cutoff = format_date(item.get("knowledge_cutoff"))
                            row.expiration_date = format_date(item.get("expiration_date"))
                            row.is_available = True
                            row.last_sync_at = local_time()
                            self.db.add(row)

                        disabled_main_names: set[str] = set()
                        disabled_main_uids: set[str] = set()
                        for model_id, row in saved_by_model_id.items():
                            # Deleted models keep their is_available frozen, matched or not.
                            if model_id not in fetched_model_ids and row.deleted_at is None:
                                row.is_available = False
                                if row.is_main:
                                    disabled_main_names.add(row.name)
                                    disabled_main_uids.add(row.uid)

                        if model_type == "text" and disabled_main_names:
                            setting_rows = await query(
                                db=self.db,
                                table=DfEngineSettings,
                                filters=(DfEngineSettings.key.in_(["assistant_model", "enhancer_model"]),),  # type: ignore
                            )
                            previous = {row.key: (json.loads(row.value) if row.value else None) for row in setting_rows}
                            cleared = False
                            for row in setting_rows:
                                stored = json.loads(row.value) if row.value else None
                                # New shape: {"uid", "name"} — match on uid. Legacy shape: bare name string.
                                matched = (
                                    stored.get("uid") in disabled_main_uids
                                    if isinstance(stored, dict)
                                    else stored in disabled_main_names
                                )
                                if matched:
                                    row.value = json.dumps(None)
                                    row.updated_at = local_time()
                                    cleared = True

                            if cleared:
                                incoming = {
                                    row.key: (json.loads(row.value) if row.value else None) for row in setting_rows
                                }
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
                                await delete_pattern(self.redis, cache_key.setting_global())
                                await delete_pattern(self.redis, cache_key.setting_logs_pattern())
                                logging.info(
                                    f"user={self.user['user_id']} sync nulled engine setting refs "
                                    f"for unavailable models {sorted(disabled_main_names)}"
                                )
                    except Exception as exc:
                        error_message = str(exc)
                    finally:
                        nickname = await query(
                            db=self.db,
                            table=Employees,
                            columns=(Employees.nickname,),
                            filters=(Employees.user_id == self.user["user_id"],),
                            fetch_one=True,
                        )
                        self.db.add(
                            DfEngineOpenrouterLogs(
                                name=nickname,
                                method="GET",
                                endpoint=endpoint,
                                request_headers=request_headers,
                                request_payload=None,
                                response_status_code=response_status_code,
                                response_headers=response_headers,
                                response_body=response_body or None,
                                error_message=error_message,
                                duration_ms=int((time.perf_counter() - started_at) * 1000),
                            )
                        )
                    await self.db.flush()

            await delete_pattern(self.redis, cache_key.model_pagination_pattern())
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
