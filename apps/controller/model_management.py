import json
import time
import traceback
from datetime import timedelta
from sqlalchemy.orm import load_only
from schemas.format.model_options import ModelAction, ModelRecord
from typing import Optional, Literal
from uuid import UUID, uuid4
from fastapi import status, Depends, Path, Query, Request
from fastapi_controller import controller
from sqlalchemy import func
from apps.controller.core import CoreDependencies
from apps.dependency.rate_limitter import rate_limit
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
from services.mysql.model import (
    DfEngineExternalApiCalls,
    DfEngineSettingLogs,
    DfEngineSettings,
    Employees,
    Users,
    DfEngineGuardrailValidations,
    DfEngineGenerations,
    DfEngineChatAssistants,
)
from utils.formatter import format_date, format_datetime


class ModelManagementController(CoreDependencies):
    @controller.get(
        "/models/{model_uid}",
        summary="Get models detail.",
        description=(
            "Shows all stored details of one AI model still offered by the provider, including whether it's "
            "enabled, main or removed, and which actions are allowed on it. Removed models can be viewed too; "
            "unavailable ones are reported as not found."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_with_model_uid_to_fetch_model_detail(
        self, model_uid: UUID = Path(description="Model UID.")
    ) -> Response:
        response = Response()
        context = f"[get-models-detail] user={self.user['user_id']} model_uid={model_uid}"
        try:
            key = self.cache_key.model_detail(model_uid)
            cached = await get_json(self.redis, key)
            if cached:
                logging.info(f"{context} succeeded source=cache")
                response.data = cached
                return response

            model = await self.model_option_repo.get_model(
                filters=(DfEngineModelOptions.uid == str(model_uid), DfEngineModelOptions.is_available.is_(True))  # type: ignore
            )
            record = ModelRecord.format(model).model_dump()
            await set_json(self.redis, key, record)
            logging.info(f"{context} succeeded source=db")
            response.data = record
        except BaseError as e:
            logging.warning(f"{context} rejected status={e.status_code} reason={e.message}")
            raise
        except Exception:
            logging.exception(f"{context} failed")
            raise ServiceError()
        return response

    @controller.get(
        "/models-price/{model_uid}",
        summary="Get models price.",
        description=(
            "Shows one AI model's average real cost per call over the trailing 90 days, in USD and IDR. "
            "Covers generations, chat assistant replies, and guardrail checks that had a cost. "
            "Shows zero when there were no such calls."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_with_model_uid_to_fetch_model_price(
        self, model_uid: UUID = Path(description="Model UID.")
    ) -> Response:
        response = Response()
        context = f"[get-models-price] user={self.user['user_id']} model_uid={model_uid}"
        try:
            cached = await get_json(self.redis, self.cache_key.model_detail(model_uid))
            if cached:
                model_id = cached["id"]
            else:
                model_id = await self.model_option_repo.get_model(
                    columns=(DfEngineModelOptions.id,),
                    filters=(DfEngineModelOptions.uid == str(model_uid),),
                )

            since = local_time() - timedelta(days=90)
            total_cost = 0.0
            total_calls = 0
            for table, fetch in (
                (DfEngineGenerations, self.generation_repo.get_generation),
                (DfEngineChatAssistants, self.chat_assistant_repo.get_chat_assistant),
                (DfEngineGuardrailValidations, self.guardrail_validation_repo.get_guardrail_validation),
            ):
                usage = await fetch(
                    columns=(func.coalesce(func.sum(table.cost), 0).label("cost"), func.count().label("calls")),
                    filters=(table.model_id == model_id, table.cost > 0, table.created_at >= since),  # type: ignore
                )
                total_cost += float(usage["cost"])
                total_calls += usage["calls"]

            usd_cost = total_cost / total_calls if total_calls else 0
            idr_cost = usd_cost / await self.currency_repo.get_usd_rate()
            response.data = {
                "usd": f"USD {usd_cost:.4f}" if usd_cost else "USD 0",
                "idr": f"IDR {idr_cost:,.0f}".replace(",", "."),
            }
            logging.info(f"{context} succeeded calls={total_calls}")
        except BaseError as e:
            logging.warning(f"{context} rejected status={e.status_code} reason={e.message}")
            raise
        except Exception:
            logging.exception(f"{context} failed")
            raise ServiceError()
        return response

    @controller.get(
        "/models",
        summary="Get models.",
        description=(
            "Returns AI models still available from the provider, paginated and sorted by type, then name. "
            "Pass `type` to restrict to one kind of model, `search` to filter by name, and/or "
            "`is_enabled=true` to view only enabled ones. Removed models are included unless "
            "`is_deleted=true` is passed, which lists only the removed ones."
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
            description="Search text to filter models by name (case-insensitive, substring match). Omit to list all.",
            examples=["gemini"],
        ),
        is_enabled: Optional[bool] = Query(
            default=None,
            description="Pass true to list only enabled models. Omit or pass false to include both enabled and disabled models.",
        ),
        is_deleted: Optional[bool] = Query(
            default=None,
            description=(
                "Pass true to list only soft-deleted models (the recovery view). Omit or pass false to include "
                "both deleted and non-deleted models. Only available models are returned either way."
            ),
        ),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=500, ge=1, le=500, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        context = (
            f"[get-models] user={self.user['user_id']} type={type} search={search!r} "
            f"is_enabled={is_enabled} is_deleted={is_deleted} page={page} items_per_page={itemsPerPage}"
        )
        filters = (DfEngineModelOptions.is_available.is_(True),)  # type: ignore
        try:
            key = self.cache_key.model_pagination_refactored(
                page=page,
                itemsPerPage=itemsPerPage,
                type=type,
                search=search,
                is_enabled=is_enabled,
                is_deleted=is_deleted,
            )
            cached = await get_json(self.redis, key)
            if cached:
                logging.info(
                    f"{context} succeeded source=cache count={len(cached['paginated'])} total={cached['totalData']}"
                )
                response.data = cached
                return response

            if type:
                filters += (DfEngineModelOptions.type == type,)  # type: ignore
            if search:
                filters += (DfEngineModelOptions.name.ilike(f"%{search}%"),)  # type: ignore
            if is_enabled:
                filters += (DfEngineModelOptions.is_enabled.is_(is_enabled),)  # type: ignore
            if is_deleted:
                filters += (
                    DfEngineModelOptions.deleted_at.is_not(None)
                    if is_deleted
                    else DfEngineModelOptions.deleted_at.is_(None),
                )  # type: ignore

            total_data = await self.model_option_repo.get_model(
                columns=(func.count(DfEngineModelOptions.id),),  # type: ignore
                filters=filters,
                raise_if_null=False,
            )
            records = await self.model_option_repo.get_model(
                filters=filters,
                order_by=(DfEngineModelOptions.type.asc(), DfEngineModelOptions.name.asc()),  # type: ignore
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
                fetch_one=False,
                raise_if_null=False,
            )

            result = PaginationResponse(
                paginated=[ModelRecord.format(record).model_dump() for record in records],
                totalData=total_data or 0,
            ).model_dump()
            await set_json(self.redis, key, result)
            logging.info(f"{context} succeeded source=db count={len(records)} total={total_data}")
            response.data = result
        except BaseError as e:
            logging.warning(f"{context} rejected status={e.status_code} reason={e.message}")
            raise
        except Exception:
            logging.exception(f"{context} failed")
            raise ServiceError()
        return response

    @controller.patch(
        "/models/{model_uid}",
        summary="Set enable disable model.",
        description=(
            "Turns a model on or off for selection. Rejected if the model is removed or no longer offered "
            "by the provider. The main model can't be disabled. Main status and engine settings "
            "are not changed. Returns the updated model."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_set_enable_disable(
        self,
        schema: SetModelEnabledPayload,
        model_uid: UUID = Path(
            ...,
            description="Model UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        context = (
            f"[set-model-enabled] user={self.user['user_id']} model_uid={model_uid} is_enabled={schema.is_enabled}"
        )
        filters = (DfEngineModelOptions.uid == str(model_uid),)
        try:
            model = await get_json(self.redis, self.cache_key.model_detail(model_uid))
            source = "cache"
            if not model:
                record = await self.model_option_repo.get_model(filters=filters)
                model = ModelRecord.format(record).model_dump()
                source = "db"

            if model["deleted_at"] is not None:
                raise DataValidationError(message="model_option_deleted_cannot_set_enabled")
            if model["is_available"] is False:
                raise DataValidationError(message="model_option_unavailable_cannot_set_enabled")
            if model["is_main"] and not schema.is_enabled:
                raise DataValidationError(message="model_option_main_cannot_be_disabled")

            await self.model_option_repo.update(filters=filters, values={"is_enabled": schema.is_enabled})
            await self.db.commit()
            await delete_pattern(self.redis, self.cache_key.models_pattern())
            logging.info(f"{context} succeeded source={source}")
            model["is_enabled"] = schema.is_enabled
            model["action"] = ModelAction.action(model)
            response.data = ModelRecord(**model).model_dump()
        except BaseError as e:
            logging.warning(f"{context} rejected status={e.status_code} reason={e.message}")
            raise
        except Exception:
            logging.exception(f"{context} failed")
            raise ServiceError()
        return response

    @controller.delete(
        "/models/{uid}",
        summary="Delete model.",
        description=(
            "Removes a model without permanently erasing it, so it can be recovered later. Only works on "
            "a model that's still offered by the provider, disabled, not set as main, and not already "
            "removed. Returns the updated model."
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
        context = f"[delete-model] user={self.user['user_id']} model_uid={uid}"
        filters = (DfEngineModelOptions.uid == str(uid),)
        try:
            model = await get_json(self.redis, self.cache_key.model_detail(uid))
            source = "cache"
            if not model:
                record = await self.model_option_repo.get_model(filters=filters)
                model = ModelRecord.format(record).model_dump()
                source = "db"

            if model["deleted_at"] is not None:
                raise DataValidationError(message="model_option_already_deleted")
            if model["is_main"]:
                raise DataValidationError(message="model_option_main_cannot_be_deleted")
            if model["is_enabled"]:
                raise DataValidationError(message="model_option_active_cannot_be_deleted")
            if model["is_available"] is False:
                raise DataValidationError(message="model_option_unavailable_cannot_be_deleted")

            values = {"deleted_at": local_time(), "deleted_by": int(self.user["user_id"])}
            await self.model_option_repo.update(filters=filters, values=values)
            await self.db.commit()
            await delete_pattern(self.redis, self.cache_key.models_pattern())

            logging.info(f"{context} succeeded source={source} model_id={model['model_id']}")
            model.update(deleted_at=format_datetime(values["deleted_at"]), deleted_by=values["deleted_by"])
            model["action"] = ModelAction.action(model)
            response.data = ModelRecord(**model).model_dump()
        except BaseError as e:
            logging.warning(f"{context} rejected status={e.status_code} reason={e.message}")
            raise
        except Exception:
            logging.exception(f"{context} failed")
            raise ServiceError()
        return response

    @controller.patch(
        "/models/{uid}/recover",
        summary="Recover model.",
        description=(
            "Restores a previously removed model. Only works on a model that's currently removed. "
            "Its availability reflects the last time models were synced, so run a sync to refresh it. "
            "Returns the updated model."
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
        context = f"[recover-model] user={self.user['user_id']} model_uid={uid}"
        filters = (DfEngineModelOptions.uid == str(uid),)
        try:
            model = await get_json(self.redis, self.cache_key.model_detail(uid))
            source = "cache"
            if not model:
                record = await self.model_option_repo.get_model(filters=filters)
                model = ModelRecord.format(record).model_dump()
                source = "db"

            if model["deleted_at"] is None:
                raise DataValidationError(message="model_option_not_deleted")

            values = {"deleted_at": None, "deleted_by": None}
            await self.model_option_repo.update(filters=filters, values=values)
            await self.db.commit()
            await delete_pattern(self.redis, self.cache_key.models_pattern())

            logging.info(f"{context} succeeded source={source} model_id={model['model_id']}")
            model.update(values)
            model["action"] = ModelAction.action(model)
            response.data = ModelRecord(**model).model_dump()
        except BaseError as e:
            logging.warning(f"{context} rejected status={e.status_code} reason={e.message}")
            raise
        except Exception:
            logging.exception(f"{context} failed")
            raise ServiceError()
        return response

    @controller.post(
        "/models",
        summary="Sync openrouter models.",
        description=(
            "Pulls the latest text, video, and image model lists from the provider and updates our "
            "records. New models are added as disabled, existing ones (including removed ones) are "
            "refreshed, and ones no longer offered are marked unavailable instead of being erased. "
            "Enabled, main, and removed states are kept. A type whose request fails or returns no models "
            "is skipped, and the sync still reports success. After the text sync, the enhancer or assistant "
            "model setting is reset to blank if its model isn't an available text model, and that change "
            "is recorded in the setting logs. Every provider call, success or failure, is logged. "
            "Limited to 1 request per minute."
        ),
        dependencies=[
            Depends(
                rate_limit(
                    times=1,
                    seconds=60,
                    message="model_sync_rate_limit_exceeded",
                    context={"times": 1, "seconds": 60},
                )
            )
        ],
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
    )
    async def model_management_to_sync_available_models(self, request: Request) -> Response:
        response = Response()
        context = f"[sync-models] user={self.user['user_id']}"
        request_headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
        endpoints = {
            "text": "/models?output_modalities=text",
            "video": "/videos/models",
            "image": "/images/models",
        }
        try:
            async with APICaller(base_url=OPENROUTER_BASE_URL, headers=request_headers) as caller:
                for model_type, endpoint in endpoints.items():
                    openrouter_response = await caller.openrouter("GET", endpoint, self.user["user_id"])
                    if openrouter_response.status_code != 200:
                        logging.warning(f"{context} skipped type={model_type} status={openrouter_response.status_code}")
                        continue

                    items = {
                        item["id"]: item for item in openrouter_response.json().get("data") or [] if item.get("id")
                    }
                    if not items:
                        logging.warning(f"{context} skipped type={model_type} reason=empty_model_list")
                        continue

                    synced_at = local_time()
                    rows = [
                        {
                            "uid": str(uuid4()),
                            "model_id": model_id,
                            "type": model_type,
                            "is_main": False,
                            "is_enabled": False,
                            "is_available": True,
                            "last_sync_at": synced_at,
                            "name": item.get("name") or model_id,
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
                            "knowledge_cutoff": format_date(item.get("knowledge_cutoff")),
                            "expiration_date": format_date(item.get("expiration_date")),
                        }
                        for model_id, item in items.items()
                    ]
                    await self.model_option_repo.upsert(
                        rows, keep_columns=("uid", "model_id", "type", "is_main", "is_enabled")
                    )
                    await self.model_option_repo.update(
                        filters=(
                            DfEngineModelOptions.type == model_type,
                            DfEngineModelOptions.model_id.not_in(list(items)),  # type: ignore
                        ),
                        values={"is_available": False},
                    )

                    dangling = []
                    if model_type == "text":
                        setting_filters = (
                            DfEngineSettings.code == "admin_setting",
                            DfEngineSettings.key.in_(["enhancer_model", "assistant_model"]),  # type: ignore
                        )
                        settings = await self.admin_repo.get_setting(
                            filters=setting_filters, fetch_one=False, raise_if_null=False
                        )
                        for setting in settings:
                            stored = setting["value"]
                            if not stored:
                                continue
                            match = (
                                DfEngineModelOptions.uid == stored["uid"]
                                if isinstance(stored, dict)
                                else DfEngineModelOptions.name == stored
                            )
                            available = await self.model_option_repo.get_model(
                                columns=(DfEngineModelOptions.id,),
                                filters=(
                                    match,
                                    DfEngineModelOptions.type == "text",
                                    DfEngineModelOptions.is_available.is_(True),  # type: ignore
                                ),
                                raise_if_null=False,
                            )
                            if available is None:
                                dangling.append(setting["key"])

                        if dangling:
                            await self.admin_repo.update(
                                filters=(*setting_filters, DfEngineSettings.key.in_(dangling)),  # type: ignore
                                values={"value": json.dumps(None), "updated_at": local_time()},
                            )
                            previous = {setting["key"]: setting["value"] for setting in settings}
                            user = await query(
                                db=self.db,
                                table=Users,
                                options=(load_only(Users.email, Users.username),),  # type: ignore
                                filters=(Users.id == int(self.user["user_id"]),),  # type: ignore
                                fetch_one=True,
                            )
                            self.db.add(
                                DfEngineSettingLogs(
                                    created_by=int(self.user["user_id"]),
                                    user_email=user.email if user else None,
                                    user_name=user.username if user else None,
                                    previous_data=previous,
                                    incoming_data={**previous, **dict.fromkeys(dangling)},
                                    ip_address=(
                                        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                                        or (request.client.host if request.client else None)
                                    ),
                                    user_agent=request.headers.get("User-Agent"),
                                )
                            )
                            logging.info(f"{context} cleared unavailable setting models={dangling}")

                    await self.db.commit()
                    await delete_pattern(self.redis, self.cache_key.models_pattern())
                    if dangling:
                        for pattern in (
                            self.cache_key.setting_global(),
                            self.cache_key.setting_logs_pattern(),
                            self.cache_key.setting_project_pattern(),
                        ):
                            await delete_pattern(self.redis, pattern)
                    logging.info(f"{context} synced type={model_type} fetched={len(rows)}")
        except BaseError as e:
            logging.warning(f"{context} rejected status={e.status_code} reason={e.message}")
            raise
        except Exception:
            logging.exception(f"{context} failed")
            raise ServiceError()
        return response
