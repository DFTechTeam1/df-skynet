import traceback
from typing import Any, Optional
from uuid import uuid4, UUID
from fastapi import status, Depends, Path, Query
from fastapi_controller import controller
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.feature_management import FeaturePayload
from services.mysql.model import (
    DfEngineActionMappings,
    DfEngineActions,
    DfEnginePromptTemplates,
    Users,
    Employees,
)
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError
from utils.serializer import serialize
from utils.formatter import format_datetime, format_creator
# from apps.dependency.permission import require_permissions

feature_permission = {
    "fetch_features": "fetch_features",
    "create_feature": "create_feature",
    "update_feature": "update_feature",
    "delete_feature": "delete_feature",
}


class FeatureManagementController(CoreDependencies):
    async def features(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """Fetch features (newest first) shaped for the frontend: formatted
        timestamps, resolved `creater`/`updater`, a nested `templates` array
        built from `df_engine_action_mappings`, and an `action` block
        reflecting what the current user is permitted to do. Both active and
        inactive features are returned — unlike prompt templates, the
        feature-management screen manages (and toggles) inactive rows too,
        it doesn't just pick from active ones. Shared by every endpoint below
        so each mutation can hand back fresh, complete state instead of the
        frontend re-fetching separately.

        `name`, if given, filters to features whose name contains it
        (case-insensitive) — this is what backs the search endpoint.
        """
        query = select(DfEngineActions)
        if name:
            query = query.where(DfEngineActions.name.ilike(f"{name}%"))  # type: ignore

        records = (
            (
                await self.db.execute(
                    query.options(
                        selectinload(DfEngineActions.created_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(DfEngineActions.updated_by_user)  # type: ignore
                        .load_only(Users.image)  # type: ignore
                        .selectinload(Users.employees)  # type: ignore
                        .load_only(Employees.nickname),  # type: ignore
                        selectinload(  # type: ignore
                            DfEngineActions.df_engine_action_mappings
                        ).selectinload(
                            DfEngineActionMappings.df_engine_prompt_templates
                        ),  # type: ignore
                    ).order_by(DfEngineActions.created_at.desc())  # type: ignore
                )
            )
            .scalars()
            .all()
        )

        features = [record for record in serialize(records)]
        permissions = self.user.get("permissions", [])
        for feature in features:
            feature["created_at"] = format_datetime(feature["created_at"])
            feature["updated_at"] = format_datetime(feature["updated_at"])
            feature["creater"] = format_creator(feature["created_by_user"])
            feature["updater"] = format_creator(feature["updated_by_user"])

            templates = []
            for mapping in feature.get("df_engine_action_mappings") or []:
                template = mapping.get("df_engine_prompt_templates") or {}
                templates.append(
                    {
                        "mapping_uid": mapping.get("uid"),
                        "uid": template.get("uid"),
                        "name": template.get("name"),
                        "description": template.get("description"),
                        "is_active": template.get("is_active"),
                    }
                )
            feature["templates"] = templates

            feature["action"] = {
                "can_fetch_features": feature_permission["fetch_features"]
                in permissions,
                "can_create_feature": feature_permission["create_feature"]
                in permissions,
                "can_update_feature": feature_permission["update_feature"]
                in permissions,
                "can_delete_feature": feature_permission["delete_feature"]
                in permissions,
            }

            feature.pop("id", None)
            feature.pop("created_by_user", None)
            feature.pop("updated_by_user", None)
            feature.pop("created_by", None)
            feature.pop("updated_by", None)
            feature.pop("df_engine_action_mappings", None)

        return features

    async def get_feature(self, uid: UUID) -> DfEngineActions:
        record = (
            await self.db.execute(
                select(DfEngineActions).where(DfEngineActions.uid == str(uid))  # type: ignore
            )
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="feature_not_found")
        return record

    async def get_templates_by_uid(
        self, uids: list[UUID]
    ) -> dict[str, DfEnginePromptTemplates]:
        wanted = [str(uid) for uid in uids]
        if not wanted:
            return {}

        found = (
            (
                await self.db.execute(
                    select(DfEnginePromptTemplates).where(
                        DfEnginePromptTemplates.uid.in_(wanted)  # type: ignore
                    )
                )
            )
            .scalars()
            .all()
        )
        templates_by_uid = {template.uid: template for template in found}
        missing = [uid for uid in wanted if uid not in templates_by_uid]
        if missing:
            raise DataNotFoundError(
                message="feature_template_not_found",
                error={"template_uids": missing},
            )
        return templates_by_uid

    @controller.get(
        "/api/feature-management",
        summary="List or search features.",
        description=(
            "Returns features (`df_engine_actions` rows), newest first — both active and "
            "inactive, since this screen manages and toggles inactive features too, unlike "
            "prompt templates. Pass `name` to search — only features whose name contains "
            "that text (case-insensitive) are returned, in the exact same shape as the "
            "unfiltered list. Each feature includes a nested `templates` array built from "
            "`df_engine_action_mappings` — one feature can list many templates, and the "
            "same template can appear under many different features. Each template entry "
            "carries its own `mapping_uid` (the join row's uid), used internally when a "
            "later update unlinks it. Each feature also includes its resolved `creater` / "
            "`updater` and an `action` block reflecting which feature-management actions "
            "the current user is permitted to perform."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_features"])) # Will be enabled later
        # ]
    )
    async def feature_management_to_fetch_features(
        self,
        name: Optional[str] = Query(
            default=None,
            min_length=1,
            description="Search text to filter features by name (case-insensitive, partial match). Omit to list all.",
            examples=["Enhance prompt"],
        ),
    ) -> Response:
        response = Response()
        try:
            response.data = await self.features(name=name)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/api/feature-management",
        summary="Create a feature.",
        description=(
            "Registers a new feature (`df_engine_actions` row) and, in the same call, "
            "links it to the prompt templates given in `template_uids` — every uid must "
            "reference an existing prompt template, or the whole request fails. "
            "`template_uids` has no minimum length: omit it (or pass an empty list) to "
            "create a feature with no linked template yet, or pass one or many to wire "
            "them up immediately. `name` must be unique across all existing features. The "
            "record's `created_by` is taken from the authenticated user resolved from the "
            "bearer token, not from the request body. Returns the full, up-to-date list of "
            "features, so the frontend can refresh its list without a separate re-fetch."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["create_feature"])) # Will be enabled later
        # ]
    )
    async def feature_management_to_create_feature(
        self, schema: FeaturePayload
    ) -> Response:
        response = Response()
        try:
            templates_by_uid = await self.get_templates_by_uid(schema.template_uids)

            feature = DfEngineActions(
                uid=str(uuid4()),
                name=schema.name,
                description=schema.description,
                is_active=schema.is_active,
                created_by=int(self.user["user_id"]),
            )
            self.db.add(feature)
            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="feature_already_exists")

            for template in templates_by_uid.values():
                self.db.add(
                    DfEngineActionMappings(
                        uid=str(uuid4()),
                        action_id=feature.id,
                        template_id=template.id,
                    )
                )
            await self.db.flush()

            response.data = await self.features()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/api/feature-management/{uid}",
        summary="Update a feature.",
        description=(
            "Replaces the feature identified by `uid` — the request body carries the full "
            "record (`name`, `description`, `is_active`, `template_uids`), not a partial "
            "diff. `template_uids` is the complete desired set of linked prompt templates: "
            "any currently linked template missing from the list is unlinked, any new uid "
            "is linked, and unchanged ones are left untouched (their `mapping_uid` is "
            "preserved). It has no minimum length — pass an empty list to unlink every "
            "template from the feature. `name` must remain unique across all existing "
            "features. The record's `updated_by` is taken from the authenticated user "
            "resolved from the bearer token, not from the request body. Returns the full, "
            "up-to-date list of features."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["update_feature"])) # Will be enabled later
        # ]
    )
    async def feature_management_to_update_feature(
        self,
        schema: FeaturePayload,
        uid: UUID = Path(
            ...,
            description="Feature UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            feature = await self.get_feature(uid)
            templates_by_uid = await self.get_templates_by_uid(schema.template_uids)

            feature.name = schema.name
            feature.description = schema.description
            feature.is_active = schema.is_active
            feature.updated_by = int(self.user["user_id"])

            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="feature_already_exists")

            desired_ids = {template.id for template in templates_by_uid.values()}

            existing_mappings = (
                (
                    await self.db.execute(
                        select(DfEngineActionMappings).where(
                            DfEngineActionMappings.action_id == feature.id  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_by_template_id = {
                mapping.template_id: mapping for mapping in existing_mappings
            }

            for template_id, mapping in existing_by_template_id.items():
                if template_id not in desired_ids:
                    await self.db.delete(mapping)

            for template_id in desired_ids:
                if template_id not in existing_by_template_id:
                    self.db.add(
                        DfEngineActionMappings(
                            uid=str(uuid4()),
                            action_id=feature.id,
                            template_id=template_id,
                        )
                    )

            await self.db.flush()

            response.data = await self.features()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.delete(
        "/api/feature-management/{uid}",
        summary="Delete a feature.",
        description=(
            "Permanently deletes the feature identified by `uid`, along with every "
            "`df_engine_action_mappings` row linking it to a prompt template — there's no "
            "separate unlink step, deleting a feature removes it entirely. Returns the "
            "full, up-to-date list of remaining features."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["delete_feature"])) # Will be enabled later
        # ]
    )
    async def feature_management_to_delete_feature(
        self,
        uid: UUID = Path(
            ...,
            description="Feature UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            feature = await self.get_feature(uid)

            mappings = (
                (
                    await self.db.execute(
                        select(DfEngineActionMappings).where(
                            DfEngineActionMappings.action_id == feature.id  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            for mapping in mappings:
                await self.db.delete(mapping)

            await self.db.delete(feature)
            await self.db.flush()

            response.data = await self.features()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
