import traceback
from typing import Any, Optional
from uuid import uuid4, UUID
from fastapi import status, Depends, Path, Query
from fastapi_controller import controller
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, load_only
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.prompt_template import PromptTemplatePayload
from services.mysql.model import DfEnginePromptTemplates, DfEngineFeaturePromptMappings, Users, Employees
from services.redis import get_json, set_json, delete_pattern
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees
# from apps.dependency.permission import require_permissions

template_permission = {
    "fetch_df_engine_prompt_templates": "fetch_df_engine_prompt_templates",
    "update_df_engine_prompt_template": "update_df_engine_prompt_template",
    "delete_df_engine_prompt_template": "delete_df_engine_prompt_template",
}

CACHE_TTL_SECONDS = 3600
LIST_CACHE_PATTERN = "prompt_template:list:*"
# Deactivating a template unlinks it from every feature (df_engine_feature_prompt_mappings),
# and feature_management's cached `templates` arrays embed that same join
# table — so a deactivation here has to reach into that controller's cache
# namespace too, or a deactivated template can keep showing up there until
# its own TTL expires.
FEATURE_MANAGEMENT_LIST_CACHE_PATTERN = "feature_management:list:*"


def list_cache_key(name: Optional[str]) -> str:
    return f"prompt_template:list:{(name or '').strip().lower() or 'all'}"


def detail_cache_key(uid: str) -> str:
    return f"prompt_template:detail:{uid}"


class PromptTemplateController(CoreDependencies):
    def query_options(self):
        return (
            selectinload(DfEnginePromptTemplates.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEnginePromptTemplates.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        )

    def format_response(self, template: dict[str, Any], permissions: list[str]) -> dict[str, Any]:
        template["created_at"] = format_datetime(template["created_at"])
        template["updated_at"] = format_datetime(template["updated_at"])
        template["creator"] = format_user_employees(template["created_by_user"])
        template["updater"] = format_user_employees(template["updated_by_user"])
        template["action"] = {
            "can_fetch_df_engine_prompt_templates": template_permission["fetch_df_engine_prompt_templates"]
            in permissions,
            "can_delete_df_engine_prompt_template": template_permission["delete_df_engine_prompt_template"]
            in permissions,
            "can_update_df_engine_prompt_template": template_permission["update_df_engine_prompt_template"]
            in permissions,
        }

        template.pop("id", None)
        template.pop("created_by_user", None)
        template.pop("updated_by_user", None)
        template.pop("created_by", None)
        template.pop("updated_by", None)
        return template

    async def prompt_templates(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """Fetch prompt templates (active and inactive, newest first) shaped
        for the frontend: formatted timestamps, resolved `creator`/`updater`,
        and an `action` block reflecting what the current user is permitted
        to do. Shared by every endpoint below so each mutation can hand back
        fresh, complete state instead of the frontend re-fetching separately.

        `name`, if given, filters to templates whose name contains it
        (case-insensitive) — this is what backs the search endpoint.

        Raw (pre-`format_response`) rows are cached in Redis keyed by the
        normalized `name` filter — cached data has no per-user info, so it's
        safe to share across requests. `format_response` still runs on every
        call to compute the requesting user's own `action` permissions.
        """
        cache_key = list_cache_key(name)
        raw = await get_json(self.redis, cache_key)
        if raw is None:
            query = select(DfEnginePromptTemplates)
            if name:
                query = query.where(DfEnginePromptTemplates.name.ilike(f"{name}%"))  # type: ignore

            records = (
                (
                    await self.db.execute(
                        query.options(*self.query_options()).order_by(  # type: ignore
                            DfEnginePromptTemplates.created_at.desc()  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            raw = serialize(records)
            await set_json(self.redis, cache_key, raw, ttl=CACHE_TTL_SECONDS)

        permissions = self.user.get("permissions", [])
        return [self.format_response(template, permissions) for template in raw]

    async def get_prompt_template(self, uid: UUID) -> DfEnginePromptTemplates:
        record = (
            await self.db.execute(
                select(DfEnginePromptTemplates).where(
                    DfEnginePromptTemplates.uid == str(uid)  # type: ignore
                )
            )
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="prompt_template_not_found")
        return record

    async def prompt_template_detail(self, uid: UUID) -> dict[str, Any]:
        """Fetch a single prompt template by `uid` (active or inactive),
        shaped identically to an entry from `prompt_templates()`.
        """
        cache_key = detail_cache_key(str(uid))
        raw = await get_json(self.redis, cache_key)
        if raw is None:
            record = (
                await self.db.execute(
                    select(DfEnginePromptTemplates)
                    .where(
                        DfEnginePromptTemplates.uid == str(uid),  # type: ignore
                    )
                    .options(*self.query_options())  # type: ignore
                )
            ).scalar_one_or_none()
            if record is None:
                raise DataNotFoundError(message="prompt_template_not_found")
            raw = serialize(record)
            await set_json(self.redis, cache_key, raw, ttl=CACHE_TTL_SECONDS)

        permissions = self.user.get("permissions", [])
        return self.format_response(raw, permissions)

    @controller.get(
        "/prompt-management/{uid}",
        summary="Details of a prompt templates.",
        description=(
            "Returns a single prompt template identified by `uid` (active or inactive), in the exact "
            "same shape as an entry from the list endpoint. Includes its resolved "
            "`creator` / `updater` (`image` from the user, `nickname` from their linked "
            "employee record) and an `action` block reflecting which prompt-template "
            "actions the current user is permitted to perform."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_prompt_templates"])) # Will be enabled later
        # ]
    )
    async def prompt_template_with_uid_to_fetch_detail_templates(
        self,
        uid: UUID = Path(
            ...,
            description="Template UID",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            response.data = await self.prompt_template_detail(uid)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/prompt-management",
        summary="List or search prompt templates.",
        description=(
            "Returns prompt templates (active and inactive), newest first. Pass `name` to search — only "
            "templates whose name contains that text (case-insensitive) are returned, in "
            "the exact same shape as the unfiltered list. Each record includes its "
            "resolved `creator` / `updater` (`image` from the user, `nickname` from "
            "their linked employee record) and an `action` block reflecting which "
            "prompt-template actions the current user is permitted to perform."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_df_engine_prompt_templates"])) # Will be enabled later
        # ]
    )
    async def prompt_template_to_fetch_templates(
        self,
        name: Optional[str] = Query(
            default=None,
            min_length=1,
            description="Search text to filter templates by name (case-insensitive, partial match). Omit to list all.",
            examples=["system-learning"],
        ),
    ) -> Response:
        response = Response()
        try:
            response.data = await self.prompt_templates(name=name)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/prompt-management",
        summary="Create a prompt template.",
        description=(
            "Registers a reusable prompt template holding the raw prompt text that will "
            "later be injected as the base prompt whenever the template is wired to a "
            "feature (see `df_engine_feature_prompt_mappings`). `name` must be unique across all "
            "existing templates; `prompt` content may repeat across templates (e.g. cloning "
            "a template under a new name). The record's `created_by` is taken from the "
            "authenticated user resolved from the bearer token, not from the request body. "
            "Returns the full, up-to-date list of prompt templates (including the one just "
            "created), so the frontend can refresh its list without a separate re-fetch."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["create_prompt_template"])) # Will be enabled later
        # ]
    )
    async def prompt_template_to_create_template(self, schema: PromptTemplatePayload) -> Response:
        response = Response()
        try:
            prompt_template = DfEnginePromptTemplates(
                name=schema.name,
                description=schema.description,
                is_active=schema.is_active,
                prompt=schema.prompt,
                created_by=int(self.user["user_id"]),
            )
            self.db.add(prompt_template)
            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="prompt_template_already_exists")

            logging.info(
                f"user={self.user['user_id']} created prompt template uid={prompt_template.uid} "
                f"name={prompt_template.name!r} is_active={prompt_template.is_active}"
            )

            await delete_pattern(self.redis, LIST_CACHE_PATTERN)
            response.data = await self.prompt_templates()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/prompt-management/{uid}",
        summary="Update a prompt template.",
        description=(
            "Replaces the prompt template identified by `uid` — the request body carries "
            "the full record (`name`, `description`, `is_active`, `prompt`), not a partial "
            "diff. `name` must remain unique across all existing templates. The record's "
            "`updated_by` is taken from the authenticated user resolved from the bearer "
            "token, not from the request body. Returns the full, up-to-date list of "
            "prompt templates. Setting `is_active` to `false` also removes any "
            "`df_engine_feature_prompt_mappings` rows linking this template to features, so it "
            "stops appearing in feature-management's template lists."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["update_df_engine_prompt_template"])) # Will be enabled later
        # ]
    )
    async def prompt_template_to_update_template(
        self,
        schema: PromptTemplatePayload,
        uid: UUID = Path(
            ...,
            description="Template UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            prompt_template = await self.get_prompt_template(uid)

            prompt_template.name = schema.name
            prompt_template.description = schema.description
            prompt_template.is_active = schema.is_active
            prompt_template.prompt = schema.prompt
            prompt_template.updated_by = int(self.user["user_id"])

            if not schema.is_active:
                await self.db.execute(
                    delete(DfEngineFeaturePromptMappings).where(
                        DfEngineFeaturePromptMappings.template_id == prompt_template.id  # type: ignore
                    )
                )

            try:
                await self.db.flush()
            except IntegrityError:
                # See create's comment — no manual rollback, get_db() handles it once.
                raise DataConflictError(message="prompt_template_already_exists")

            logging.info(
                f"user={self.user['user_id']} updated prompt template uid={prompt_template.uid} "
                f"name={prompt_template.name!r} is_active={prompt_template.is_active}"
            )

            await delete_pattern(self.redis, LIST_CACHE_PATTERN)
            await self.redis.delete(detail_cache_key(str(uid)))
            if not schema.is_active:
                await delete_pattern(self.redis, FEATURE_MANAGEMENT_LIST_CACHE_PATTERN)

            response.data = await self.prompt_templates()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.delete(
        "/prompt-management/{uid}",
        summary="Delete a prompt template.",
        description=(
            "Permanently deletes the prompt template identified by `uid`. Fails with a "
            "conflict if the template is still referenced by a `df_engine_feature_prompt_mappings` "
            "row (i.e. currently wired to a feature) — unmap it there first. Returns "
            "the full, up-to-date list of remaining prompt templates."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["delete_df_engine_prompt_template"])) # Will be enabled later
        # ]
    )
    async def prompt_template_to_delete_template(
        self,
        uid: UUID = Path(
            ...,
            description="Template UID.",
            examples=[
                "8d96ff4e-5c35-4329-bd5d-827e2c68599d",
                "5048ee4d-8259-4c2e-a9a1-1eee369ab0c1",
            ],
        ),
    ) -> Response:
        response = Response()
        try:
            prompt_template = await self.get_prompt_template(uid)
            template_uid, template_name = prompt_template.uid, prompt_template.name

            await self.db.delete(prompt_template)
            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="prompt_template_in_use")

            logging.info(
                f"user={self.user['user_id']} deleted prompt template uid={template_uid} name={template_name!r}"
            )

            await delete_pattern(self.redis, LIST_CACHE_PATTERN)
            await self.redis.delete(detail_cache_key(str(uid)))
            response.data = await self.prompt_templates()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
