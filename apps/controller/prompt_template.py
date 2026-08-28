import traceback
from typing import Any, Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.prompt_template import PromptTemplatePayload
from services.mysql.model import DfEnginePromptTemplates, DfEngineFeaturePromptMappings, Users, Employees
from services.redis import get_json, set_json, CacheKeys
from services.mysql import query
from log import logging
from utils import local_time
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees

template_permission = {
    "fetch_df_engine_prompt_templates": "fetch_df_engine_prompt_templates",
    "update_df_engine_prompt_template": "update_df_engine_prompt_template",
    "delete_df_engine_prompt_template": "delete_df_engine_prompt_template",
}


class PromptTemplateController(CoreDependencies):
    def options(self):
        return (
            selectinload(DfEnginePromptTemplates.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEnginePromptTemplates.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEnginePromptTemplates.df_engine_feature_prompt_mappings).load_only(  # type: ignore
                DfEngineFeaturePromptMappings.id  # type: ignore
            ),
        )

    def format(self, record: dict[str, Any]) -> dict[str, Any]:
        user_permissions = [
            "delete_df_engine_prompt_template",
            "fetch_df_engine_prompt_templates",
            "update_df_engine_prompt_template",
        ]  # will be overriden first later will be using actual user permissions

        record["created_at"] = format_datetime(record["created_at"])
        record["updated_at"] = format_datetime(record["updated_at"])
        record["creator"] = format_user_employees(record["created_by_user"])
        record["updater"] = format_user_employees(record["updated_by_user"])
        record["action"] = {
            "can_fetch_detail": template_permission["fetch_df_engine_prompt_templates"] in user_permissions,
            "can_delete": template_permission["delete_df_engine_prompt_template"] in user_permissions
            and not record["df_engine_feature_prompt_mappings"],
            "can_update": template_permission["update_df_engine_prompt_template"] in user_permissions,
        }

        record.pop("id", None)
        record.pop("created_by_user", None)
        record.pop("updated_by_user", None)
        record.pop("created_by", None)
        record.pop("updated_by", None)
        record.pop("df_engine_feature_prompt_mappings", None)

        return record

    async def rebuild_response(self) -> list[dict[str, Any]]:
        """Full, newest-first template list from the DB — used to repopulate the
        `:all` cache whenever a write finds it cold."""
        results = await query(
            db=self.db,
            table=DfEnginePromptTemplates,
            options=self.options(),
            order_by=(DfEnginePromptTemplates.created_at.desc(),),  # type: ignore
        )
        records = [self.format(record) for record in serialize(results)]
        logging.info(f"user={self.user['user_id']} rebuilt prompt template list cache count={len(records)}")
        return records

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
    )
    async def prompt_template_with_uid_to_fetch_detail_template(
        self,
        uid: UUID = Path(
            ...,
            description="Template UID",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            prompt_template_global_cache_key = cache_key.prompt_templates()
            cached_prompt_template_global = await get_json(self.redis, prompt_template_global_cache_key)
            if cached_prompt_template_global:
                template = None
                for record in cached_prompt_template_global:
                    if record["uid"] == str(uid):
                        template = record

                if not template:
                    raise DataNotFoundError(message="prompt_template_not_found")

                logging.info(f"user={self.user['user_id']} fetched prompt template uid={uid} source=list_cache")
                response.data = template
                return response

            prompt_template_detail_cache_key = cache_key.prompt_template_detail(uid)
            cached_prompt_template_detail = await get_json(self.redis, prompt_template_detail_cache_key)
            if cached_prompt_template_detail:
                logging.info(f"user={self.user['user_id']} fetched prompt template uid={uid} source=detail_cache")
                response.data = cached_prompt_template_detail
                return response

            result = await query(
                db=self.db,
                table=DfEnginePromptTemplates,
                options=self.options(),
                filters=(DfEnginePromptTemplates.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )

            if result is None:
                raise DataNotFoundError(message="prompt_template_not_found")

            serialized_record = serialize(result)
            formatted_response = self.format(serialized_record)
            await set_json(self.redis, prompt_template_detail_cache_key, formatted_response)

            logging.info(f"user={self.user['user_id']} fetched prompt template uid={uid} source=db")
            response.data = formatted_response
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
        cache_key = CacheKeys()
        try:
            prompt_template_global_cache_key = cache_key.prompt_templates()
            cached_prompt_template_global = await get_json(self.redis, prompt_template_global_cache_key)
            if cached_prompt_template_global:
                logging.info(
                    f"user={self.user['user_id']} listed prompt templates source=cache "
                    f"name={name!r} count={len(cached_prompt_template_global)}"
                )
                response.data = cached_prompt_template_global
                return response

            results = await query(
                db=self.db,
                table=DfEnginePromptTemplates,
                options=self.options(),
                filters=(DfEnginePromptTemplates.name.ilike(f"{name}%"),) if name else None,  # type: ignore
                order_by=(DfEnginePromptTemplates.created_at.desc(),),  # type: ignore
            )

            records = [self.format(record) for record in serialize(results)]
            await set_json(self.redis, prompt_template_global_cache_key, records)
            logging.info(
                f"user={self.user['user_id']} listed prompt templates source=db name={name!r} count={len(records)}"
            )
            response.data = records
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
    )
    async def prompt_template_to_create_template(self, schema: PromptTemplatePayload) -> Response:
        response = Response()
        cache_key = CacheKeys()
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

            new_record = self.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEnginePromptTemplates,
                        options=self.options(),
                        filters=(DfEnginePromptTemplates.uid == str(prompt_template.uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )
            await set_json(
                self.redis,
                cache_key.prompt_template_detail(prompt_template.uid),  # type: ignore
                new_record,
            )

            prompt_template_global_cache_key = cache_key.prompt_templates()
            cached_prompt_template_global = await get_json(self.redis, prompt_template_global_cache_key)
            if cached_prompt_template_global is not None:
                records = [new_record, *cached_prompt_template_global]
                logging.info(
                    f"user={self.user['user_id']} appended prompt template uid={prompt_template.uid} "
                    f"to list cache count={len(records)}"
                )
            else:
                records = await self.rebuild_response()

            await set_json(self.redis, prompt_template_global_cache_key, records)
            response.data = records
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
            "prompt templates. Deactivating a template (`is_active` = `false`) keeps it "
            "in the list, flagged inactive, and leaves its `df_engine_feature_prompt_mappings` "
            "rows intact."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
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
        cache_key = CacheKeys()
        try:
            template = await query(
                db=self.db,
                table=DfEnginePromptTemplates,
                options=self.options(),
                filters=(DfEnginePromptTemplates.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if template is None:
                raise DataNotFoundError(message="prompt_template_not_found")

            template.name = schema.name
            template.description = schema.description
            template.is_active = schema.is_active
            template.prompt = schema.prompt
            template.updated_by = int(self.user["user_id"])
            template.updated_at = local_time()

            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="prompt_template_already_exists")

            logging.info(
                f"user={self.user['user_id']} updated prompt template uid={template.uid} "
                f"name={template.name!r} is_active={template.is_active}"
            )

            self.db.expire(template)
            updated_template = self.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEnginePromptTemplates,
                        options=self.options(),
                        filters=(DfEnginePromptTemplates.uid == str(uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )

            await set_json(
                self.redis,
                cache_key.prompt_template_detail(uid),
                updated_template,
            )

            prompt_template_global_cache_key = cache_key.prompt_templates()
            cached_prompt_template_global = await get_json(self.redis, prompt_template_global_cache_key)

            if cached_prompt_template_global is not None:
                records = [updated_template if r["uid"] == str(uid) else r for r in cached_prompt_template_global]
                logging.info(
                    f"user={self.user['user_id']} updated prompt template uid={uid} in list cache count={len(records)}"
                )
            else:
                records = await self.rebuild_response()

            await set_json(self.redis, prompt_template_global_cache_key, records)
            response.data = records

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
        cache_key = CacheKeys()
        try:
            template = await query(
                db=self.db,
                table=DfEnginePromptTemplates,
                options=self.options(),
                filters=(DfEnginePromptTemplates.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if template is None:
                raise DataNotFoundError(message="prompt_template_not_found")

            formatted_template = self.format(serialize(template))
            if formatted_template.get("action", {}).get("can_delete", False) is False:
                raise DataConflictError(message="prompt_template_in_use")

            await self.db.delete(template)
            await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} deleted prompt template uid={template.uid} name={template.name!r}"
            )

            await self.redis.delete(cache_key.prompt_template_detail(uid))

            prompt_template_global_cache_key = cache_key.prompt_templates()
            cached_prompt_template_global = await get_json(self.redis, prompt_template_global_cache_key)

            if cached_prompt_template_global is not None:
                records = [r for r in cached_prompt_template_global if r["uid"] != str(uid)]
                logging.info(
                    f"user={self.user['user_id']} removed prompt template uid={uid} "
                    f"from list cache count={len(records)}"
                )
            else:
                records = await self.rebuild_response()

            await set_json(self.redis, prompt_template_global_cache_key, records)
            response.data = records
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
