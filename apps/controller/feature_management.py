import traceback
from typing import Any, Optional
from uuid import uuid4, UUID
from fastapi import status, Depends, Path, Query
from fastapi_controller import controller
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.feature_management import FeaturePayload
from services.mysql.model import (
    DfEngineFeaturePromptMappings,
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEnginePromptTemplates,
    Users,
    Employees,
)
from services.redis import get_json, set_json, delete_pattern
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees
# from apps.dependency.permission import require_permissions


feature_permission = {
    "fetch_df_engine_features": "fetch_df_engine_features",
    "update_df_engine_feature": "update_df_engine_feature",
    "delete_df_engine_feature": "delete_df_engine_feature",
}

CACHE_TTL_SECONDS = 3600
LIST_CACHE_PATTERN = "feature_management:list:*"


def list_cache_key(name: Optional[str]) -> str:
    return f"feature_management:list:{(name or '').strip().lower() or 'all'}"


def detail_cache_key(uid: str) -> str:
    return f"feature_management:detail:{uid}"


class FeatureManagementController(CoreDependencies):
    def query_options(self):
        return (
            selectinload(DfEngineFeatures.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineFeatures.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(  # type: ignore
                DfEngineFeatures.df_engine_feature_prompt_mappings  # type: ignore
            )
            .selectinload(DfEngineFeaturePromptMappings.df_engine_prompt_templates)  # type: ignore
            .selectinload(DfEnginePromptTemplates.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineFeatures.df_engine_feature_prompt_mappings)  # type: ignore
            .selectinload(DfEngineFeaturePromptMappings.df_engine_prompt_templates)  # type: ignore
            .selectinload(DfEnginePromptTemplates.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        )

    def format_response(self, feature: dict[str, Any], permissions: list[str]) -> dict[str, Any]:
        feature["created_at"] = format_datetime(feature["created_at"])
        feature["updated_at"] = format_datetime(feature["updated_at"])
        feature["creator"] = format_user_employees(feature["created_by_user"])
        feature["updater"] = format_user_employees(feature["updated_by_user"])

        templates = []
        for mapping in feature.get("df_engine_feature_prompt_mappings", []):
            template = mapping.get("df_engine_prompt_templates", {})
            if not template.get("is_active"):
                continue
            templates.append(
                {
                    "created_at": format_datetime(template.get("created_at")),
                    "updated_at": format_datetime(template.get("updated_at")),
                    "template_uid": template.get("uid"),
                    "name": template.get("name"),
                    "description": template.get("description"),
                    "prompt": template.get("prompt"),
                    "is_active": template.get("is_active"),
                    "creator": format_user_employees(template.get("created_by_user")),
                    "updater": format_user_employees(template.get("updated_by_user")),
                }
            )
        feature["templates"] = templates
        feature["action"] = {
            "can_fetch_detail": feature_permission["fetch_df_engine_features"] in permissions,
            "can_update_feature": feature_permission["update_df_engine_feature"] in permissions,
            "can_delete_feature": feature_permission["delete_df_engine_feature"] in permissions,
        }

        feature.pop("id", None)
        feature.pop("created_by_user", None)
        feature.pop("updated_by_user", None)
        feature.pop("created_by", None)
        feature.pop("updated_by", None)
        feature.pop("df_engine_feature_prompt_mappings", None)
        return feature

    async def get_features(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """Will fetch all features available if name not provided, ordered by latest to oldest.

        Raw (pre-`format_response`) rows are cached in Redis keyed by the
        normalized `name` filter — cached data has no per-user info, so it's
        safe to share across requests. `format_response` still runs on every
        call to compute the requesting user's own `action` permissions.
        """
        cache_key = list_cache_key(name)
        raw = await get_json(self.redis, cache_key)
        if raw is None:
            query = select(DfEngineFeatures)
            if name:
                query = query.where(DfEngineFeatures.name.ilike(f"{name}%"))  # type: ignore
            records = (
                (
                    await self.db.execute(
                        query.options(*self.query_options()).order_by(  # type: ignore
                            DfEngineFeatures.created_at.desc()  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            raw = serialize(records)
            await set_json(self.redis, cache_key, raw, ttl=CACHE_TTL_SECONDS)

        permissions = self.user.get("permissions", [])
        return [self.format_response(feature, permissions) for feature in raw]

    async def get_feature_detail(self, uid: UUID) -> dict[str, Any]:
        cache_key = detail_cache_key(str(uid))
        raw = await get_json(self.redis, cache_key)
        if raw is None:
            record = (
                await self.db.execute(
                    select(DfEngineFeatures)
                    .where(DfEngineFeatures.uid == str(uid))  # type: ignore
                    .options(*self.query_options())  # type: ignore
                )
            ).scalar_one_or_none()
            if record is None:
                raise DataNotFoundError(message="feature_not_found")
            raw = serialize(record)
            await set_json(self.redis, cache_key, raw, ttl=CACHE_TTL_SECONDS)

        permissions = self.user.get("permissions", [])
        return self.format_response(raw, permissions)

    async def get_feature(self, uid: UUID) -> DfEngineFeatures:
        record = (
            await self.db.execute(
                select(DfEngineFeatures).where(DfEngineFeatures.uid == str(uid))  # type: ignore
            )
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="feature_not_found")
        return record

    async def get_templates_by_uid(self, template_uids: list[str]) -> dict[str, int]:
        if not template_uids:
            return {}

        templates = (
            await self.db.execute(
                select(DfEnginePromptTemplates.id, DfEnginePromptTemplates.uid).where(  # type: ignore
                    DfEnginePromptTemplates.uid.in_(template_uids)  # type: ignore
                )
            )
        ).all()
        map_template: dict[str, int] = {uid: id_ for id_, uid in templates}

        if len(map_template) != len(template_uids):
            error = {
                f"template_uids.{idx}": ["prompt_template_not_found"]
                for idx, template_uid in enumerate(template_uids)
                if template_uid not in map_template
            }
            raise DataValidationError(message="feature_template_not_found", error=error)

        return map_template

    @controller.get(
        "/feature-management",
        summary="List or search features.",
        description=(
            "Returns features (`df_engine_features` rows), newest first — both active and "
            "inactive, since this screen manages and toggles inactive features too, unlike "
            "prompt templates. Pass `name` to search — only features whose name contains "
            "that text (case-insensitive) are returned, in the exact same shape as the "
            "unfiltered list. Each feature includes a nested `templates` array built from "
            "`df_engine_feature_prompt_mappings`, filtered to active templates only (inactive ones "
            "are still mapped internally but omitted from this array) — one feature can "
            "list many templates, and the same template can appear under many different "
            "features. Each feature also "
            "includes its resolved `creator` / `updater` and an `action` block reflecting "
            "which feature-management actions the current user is permitted to perform."
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
            response.data = await self.get_features(name=name)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/feature-management/{uid}",
        summary="Detail of a feature.",
        description=(
            "Returns a single feature (`df_engine_features` row) identified by `uid`, in "
            "the exact same shape as one item from the list endpoint — including its "
            "nested `templates` array, resolved `creator` / `updater`, and `action` block. "
            "404s if no feature matches `uid`."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_features"])) # Will be enabled later
        # ]
    )
    async def feature_management_with_uid_to_fetch_detail_features(
        self,
        uid: UUID = Path(
            description="Feature UID.",
            examples=["36c101d8-12a8-4e3c-bf3d-eb49a337abdd"],
        ),
    ) -> Response:
        response = Response()
        try:
            response.data = await self.get_feature_detail(uid)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/feature-management",
        summary="Create a feature.",
        description=(
            "Registers a new feature (`df_engine_features` row) and, in the same call, "
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
    async def feature_management_to_create_feature(self, schema: FeaturePayload) -> Response:
        response = Response()
        try:
            map_template = await self.get_templates_by_uid(schema.template_uids)

            feature = DfEngineFeatures(
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

            for template_id in map_template.values():
                self.db.add(
                    DfEngineFeaturePromptMappings(
                        uid=str(uuid4()),
                        feature_id=feature.id,
                        template_id=template_id,
                    )
                )
            await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} created feature uid={feature.uid} "
                f"name={feature.name!r} is_active={feature.is_active} template_count={len(map_template)}"
            )

            await delete_pattern(self.redis, LIST_CACHE_PATTERN)
            response.data = await self.get_features()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/feature-management/{uid}",
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
            "resolved from the bearer token, not from the request body. Setting `is_active` "
            "to `false` also removes any `df_engine_menu_feature_mappings` rows linking this "
            "feature to menus, so it stops appearing in menu-management's feature lists. "
            "Returns the full, up-to-date list of features."
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
            map_template = await self.get_templates_by_uid(schema.template_uids)

            feature.name = schema.name
            feature.description = schema.description
            feature.is_active = schema.is_active
            feature.updated_by = int(self.user["user_id"])

            if not schema.is_active:
                await self.db.execute(
                    delete(DfEngineMenuFeatureMappings).where(
                        DfEngineMenuFeatureMappings.feature_id == feature.id  # type: ignore
                    )
                )

            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="feature_already_exists")

            desired_ids = set(map_template.values())

            existing_mappings = (
                (
                    await self.db.execute(
                        select(DfEngineFeaturePromptMappings).where(
                            DfEngineFeaturePromptMappings.feature_id == feature.id  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_by_template_id = {mapping.template_id: mapping for mapping in existing_mappings}
            unlinked_count = len(existing_by_template_id.keys() - desired_ids)
            linked_count = len(desired_ids - existing_by_template_id.keys())

            for template_id, mapping in existing_by_template_id.items():
                if template_id not in desired_ids:
                    await self.db.delete(mapping)

            for template_id in desired_ids:
                if template_id not in existing_by_template_id:
                    self.db.add(
                        DfEngineFeaturePromptMappings(
                            uid=str(uuid4()),
                            feature_id=feature.id,
                            template_id=template_id,
                        )
                    )

            await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} updated feature uid={feature.uid} "
                f"name={feature.name!r} is_active={feature.is_active} "
                f"templates_linked={linked_count} templates_unlinked={unlinked_count}"
            )

            await delete_pattern(self.redis, LIST_CACHE_PATTERN)
            await self.redis.delete(detail_cache_key(str(uid)))
            response.data = await self.get_features()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.delete(
        "/feature-management/{uid}",
        summary="Delete a feature.",
        description=(
            "Permanently deletes the feature identified by `uid`, along with every "
            "`df_engine_feature_prompt_mappings` row linking it to a prompt template and "
            "every `df_engine_menu_feature_mappings` row linking it to a menu — there's no "
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
                        select(DfEngineFeaturePromptMappings).where(
                            DfEngineFeaturePromptMappings.feature_id == feature.id  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            for mapping in mappings:
                await self.db.delete(mapping)

            menu_mappings = (
                (
                    await self.db.execute(
                        select(DfEngineMenuFeatureMappings).where(
                            DfEngineMenuFeatureMappings.feature_id == feature.id  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            for mapping in menu_mappings:
                await self.db.delete(mapping)

            await self.db.delete(feature)
            await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} deleted feature uid={feature.uid} "
                f"name={feature.name!r} mapping_count={len(mappings)} menu_mapping_count={len(menu_mappings)}"
            )

            await delete_pattern(self.redis, LIST_CACHE_PATTERN)
            await self.redis.delete(detail_cache_key(str(uid)))
            response.data = await self.get_features()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
