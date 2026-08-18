import traceback
from typing import Any, Optional
from uuid import uuid4, UUID
from fastapi import status, Depends, Path, Query
from fastapi_controller import controller
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, load_only
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.prompt_template import CreatePromptTemplatePayload
from services.mysql.model import DfEnginePromptTemplates, Users, Employees
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError
from utils.serializer import serialize
from utils.formatter import format_datetime, format_creator
# from apps.dependency.permission import require_permissions

template_permission = {
    "create_prompt_template": "create_prompt_template",
    "fetch_prompt_templates": "fetch_prompt_templates",
    "update_prompt_template": "update_prompt_template",
    "delete_prompt_template": "delete_prompt_template",
}


class PromptTemplateController(CoreDependencies):
    def _shape_template(self, template: dict[str, Any]) -> dict[str, Any]:
        """Apply the shared display shaping (formatted timestamps, resolved
        `creater`/`updater`, `action` block) to a single serialized template
        dict, in place. Used by both the list and single-detail endpoints so
        they stay in sync.
        """
        permissions = self.user.get("permissions", [])
        template["created_at"] = format_datetime(template["created_at"])
        template["updated_at"] = format_datetime(template["updated_at"])
        template["creater"] = format_creator(template["created_by_user"])
        template["updater"] = format_creator(template["updated_by_user"])
        template["action"] = {
            "can_fetch_prompt_templates": template_permission["fetch_prompt_templates"]
            in permissions,
            "can_delete_prompt_template": template_permission["delete_prompt_template"]
            in permissions,
            "can_update_prompt_template": template_permission["update_prompt_template"]
            in permissions,
            "can_create_prompt_template": template_permission["create_prompt_template"]
            in permissions,
        }

        template.pop("id", None)
        template.pop("created_by_user", None)
        template.pop("updated_by_user", None)
        template.pop("created_by", None)
        template.pop("updated_by", None)

        return template

    async def prompt_templates(
        self, name: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Fetch active prompt templates (newest first) shaped for the frontend:
        formatted timestamps, resolved `creater`/`updater`, and an `action`
        block reflecting what the current user is permitted to do. Shared by
        every endpoint below so each mutation can hand back fresh, complete
        state instead of the frontend re-fetching separately.

        `name`, if given, filters to templates whose name contains it
        (case-insensitive) — this is what backs the search endpoint.
        """
        query = select(DfEnginePromptTemplates).where(
            DfEnginePromptTemplates.is_active == True  # type: ignore
        )
        if name:
            query = query.where(DfEnginePromptTemplates.name.ilike(f"{name}%"))  # type: ignore

        records = (
            (
                await self.db.execute(
                    query.options(
                        selectinload(DfEnginePromptTemplates.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEnginePromptTemplates.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                    ).order_by(DfEnginePromptTemplates.created_at.desc())  # type: ignore
                )
            )
            .scalars()
            .all()
        )

        templates = [record for record in serialize(records)]
        return [self._shape_template(template) for template in templates]

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
        """Fetch a single active prompt template by `uid`, shaped identically
        to an entry from `prompt_templates()`.
        """
        record = (
            await self.db.execute(
                select(DfEnginePromptTemplates)
                .where(
                    DfEnginePromptTemplates.uid == str(uid),  # type: ignore
                    DfEnginePromptTemplates.is_active == True,  # type: ignore
                )
                .options(
                    selectinload(DfEnginePromptTemplates.created_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                    selectinload(DfEnginePromptTemplates.updated_by_user)  # type: ignore
                    .load_only(Users.image)  # type: ignore
                    .selectinload(Users.employees)  # type: ignore
                    .load_only(Employees.nickname),  # type: ignore
                )
            )
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="prompt_template_not_found")

        template = serialize(record)
        return self._shape_template(template)

    @controller.get(
        "/api/prompt-management/{uid}",
        summary="Details of a prompt templates.",
        description=(
            "Returns a single active prompt template identified by `uid`, in the exact "
            "same shape as an entry from the list endpoint. Includes its resolved "
            "`creater` / `updater` (`image` from the user, `nickname` from their linked "
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
        "/api/prompt-management",
        summary="List or search prompt templates.",
        description=(
            "Returns active prompt templates, newest first. Pass `name` to search — only "
            "templates whose name contains that text (case-insensitive) are returned, in "
            "the exact same shape as the unfiltered list. Each record includes its "
            "resolved `creater` / `updater` (`image` from the user, `nickname` from "
            "their linked employee record) and an `action` block reflecting which "
            "prompt-template actions the current user is permitted to perform."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_prompt_templates"])) # Will be enabled later
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
        "/api/prompt-management",
        summary="Create a prompt template.",
        description=(
            "Registers a reusable prompt template holding the raw prompt text that will "
            "later be injected as the base prompt whenever the template is wired to a page "
            "action (see `df_engine_action_mappings`). `name` must be unique across all "
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
    async def prompt_template_to_create_template(
        self, schema: CreatePromptTemplatePayload
    ) -> Response:
        response = Response()
        try:
            prompt_template = DfEnginePromptTemplates(
                uid=str(uuid4()),
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
                # No manual rollback here — get_db()'s own except-clause already
                # rolls back the whole request once this propagates. A second,
                # redundant rollback here previously discarded more than this
                # request's own failed write under nested-savepoint (test)
                # transactions, since the session had nothing left to roll back
                # to by the time get_db's wrapper ran.
                raise DataConflictError(message="prompt_template_already_exists")

            response.data = await self.prompt_templates()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/api/prompt-management/{uid}",
        summary="Update a prompt template.",
        description=(
            "Replaces the prompt template identified by `uid` — the request body carries "
            "the full record (`name`, `description`, `is_active`, `prompt`), not a partial "
            "diff. `name` must remain unique across all existing templates. The record's "
            "`updated_by` is taken from the authenticated user resolved from the bearer "
            "token, not from the request body. Returns the full, up-to-date list of "
            "prompt templates."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["update_prompt_template"])) # Will be enabled later
        # ]
    )
    async def prompt_template_to_update_template(
        self,
        schema: CreatePromptTemplatePayload,
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

            try:
                await self.db.flush()
            except IntegrityError:
                # See create's comment — no manual rollback, get_db() handles it once.
                raise DataConflictError(message="prompt_template_already_exists")

            response.data = await self.prompt_templates()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.delete(
        "/api/prompt-management/{uid}",
        summary="Delete a prompt template.",
        description=(
            "Permanently deletes the prompt template identified by `uid`. Fails with a "
            "conflict if the template is still referenced by a `df_engine_action_mappings` "
            "row (i.e. currently wired to a page action) — unmap it there first. Returns "
            "the full, up-to-date list of remaining prompt templates."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Prompt Template Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["delete_prompt_template"])) # Will be enabled later
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

            await self.db.delete(prompt_template)
            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="prompt_template_in_use")

            response.data = await self.prompt_templates()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
