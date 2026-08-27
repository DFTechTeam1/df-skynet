import traceback
from typing import Any, Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.feature_management import FeaturePayload
from services.mysql import query
from services.mysql.model import (
    DfEngineFeaturePromptMappings,
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEnginePromptTemplates,
    Users,
    Employees,
)
from services.redis import get_json, set_json
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees


feature_permission = {
    "fetch_df_engine_features": "fetch_df_engine_features",
    "update_df_engine_feature": "update_df_engine_feature",
    "delete_df_engine_feature": "delete_df_engine_feature",
}

CACHE_TTL_SECONDS = 3600


class FeatureManagementController(CoreDependencies):
    def list_cache_key(self, name: Optional[str] = None) -> str:
        return f"feature_management:list:{(name or '').strip().lower() or 'all'}"

    def detail_cache_key(self, uid: UUID) -> str:
        return f"feature_management:detail:{uid}"

    def options(self):
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
            selectinload(DfEngineFeatures.df_engine_menu_feature_mappings).load_only(DfEngineMenuFeatureMappings.id),  # type: ignore  # type: ignore
        )

    def format(self, record: dict[str, Any]) -> dict[str, Any]:
        user_permissions = [
            "update_df_engine_feature",
            "fetch_df_engine_features",
            "delete_df_engine_feature",
        ]  # will be overriden first later will be using actual user permissions

        record["created_at"] = format_datetime(record["created_at"])
        record["updated_at"] = format_datetime(record["updated_at"])
        record["creator"] = format_user_employees(record["created_by_user"])
        record["updater"] = format_user_employees(record["updated_by_user"])

        templates = []
        for mapping in record.get("df_engine_feature_prompt_mappings", []):
            template = mapping.get("df_engine_prompt_templates", {})
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
        record["templates"] = templates
        record["action"] = {
            "can_fetch_detail": feature_permission["fetch_df_engine_features"] in user_permissions,
            "can_update": feature_permission["update_df_engine_feature"] in user_permissions,
            "can_delete": feature_permission["delete_df_engine_feature"] in user_permissions
            and not record["df_engine_menu_feature_mappings"],
        }

        record.pop("id", None)
        record.pop("created_by_user", None)
        record.pop("updated_by_user", None)
        record.pop("created_by", None)
        record.pop("updated_by", None)
        record.pop("df_engine_feature_prompt_mappings", None)
        record.pop("df_engine_menu_feature_mappings", None)
        return record

    async def rebuild_response(self) -> list[dict[str, Any]]:
        """Full, newest-first feature list from the DB — used to repopulate the
        `:all` cache whenever a write finds it cold."""
        results = await query(
            db=self.db,
            table=DfEngineFeatures,
            options=self.options(),
            order_by=(DfEngineFeatures.created_at.desc(),),  # type: ignore
        )
        records = [self.format(record) for record in serialize(results)]
        logging.info(f"user={self.user['user_id']} rebuilt feature list cache count={len(records)}")
        return records

    @controller.get(
        "/feature-management",
        summary="List or search features.",
        description=(
            "Returns features (`df_engine_features` rows), newest first — both active and "
            "inactive, since this screen manages and toggles inactive features too. Pass "
            "`name` to search — only features whose name starts with that text "
            "(case-insensitive prefix match) are returned, in the exact same shape as the "
            "unfiltered list. Each feature includes a nested `templates` array built from "
            "`df_engine_feature_prompt_mappings` — every linked prompt template, active or "
            "inactive, each carrying its own `is_active` flag. One feature can list many "
            "templates, and the same template can be linked to many different features. "
            "Each feature also includes its resolved `creator` / `updater` and an `action` "
            "block reflecting which feature-management actions the current user is "
            "permitted to perform."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
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
            list_cache_key = self.list_cache_key(name)
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list:
                logging.info(
                    f"user={self.user['user_id']} listed features source=cache name={name!r} count={len(cached_list)}"
                )
                response.data = cached_list
                return response

            results = await query(
                db=self.db,
                table=DfEngineFeatures,
                options=self.options(),
                filters=(DfEngineFeatures.name.ilike(f"{name}%"),) if name else None,  # type: ignore
                order_by=(DfEngineFeatures.created_at.desc(),),  # type: ignore
            )
            records = [self.format(record) for record in serialize(results)]
            await set_json(self.redis, list_cache_key, records, ttl=CACHE_TTL_SECONDS)

            logging.info(f"user={self.user['user_id']} listed features source=db name={name!r} count={len(records)}")
            response.data = records
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
    )
    async def feature_management_with_uid_to_fetch_detail_feature(
        self,
        uid: UUID = Path(
            description="Feature UID.",
            examples=["36c101d8-12a8-4e3c-bf3d-eb49a337abdd"],
        ),
    ) -> Response:
        response = Response()
        try:
            list_cache_key = self.list_cache_key()
            cached_global = await get_json(self.redis, list_cache_key)
            if cached_global:
                feature = None
                for record in cached_global:
                    if record["uid"] == str(uid):
                        feature = record

                if not feature:
                    raise DataNotFoundError(message="feature_not_found")

                logging.info(f"user={self.user['user_id']} fetched feature uid={uid} source=list_cache")
                response.data = feature
                return response

            detail_cache_key = self.detail_cache_key(uid)
            cached_detail = await get_json(self.redis, detail_cache_key)
            if cached_detail:
                logging.info(f"user={self.user['user_id']} fetched feature uid={uid} source=detail_cache")
                response.data = cached_detail
                return response

            result = await query(
                db=self.db,
                table=DfEngineFeatures,
                options=self.options(),
                filters=(DfEngineFeatures.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )

            if result is None:
                raise DataNotFoundError(message="feature_not_found")

            serialized_record = serialize(result)
            formatted_response = self.format(serialized_record)
            await set_json(self.redis, detail_cache_key, formatted_response, ttl=CACHE_TTL_SECONDS)

            logging.info(f"user={self.user['user_id']} fetched feature uid={uid} source=db")
            response.data = formatted_response
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
            "reference an existing prompt template, or the whole request fails with a 422 "
            "listing the offending indices. `template_uids` has no minimum length: omit it "
            "(or pass an empty list) to create a feature with no linked template yet, or "
            "pass one or many to wire them up immediately. `name` must be unique across "
            "all existing features. The record's `created_by` is taken from the "
            "authenticated user resolved from the bearer token, not from the request body. "
            "Returns the full, up-to-date list of features, so the frontend can refresh "
            "its list without a separate re-fetch."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
    )
    async def feature_management_to_create_feature(self, schema: FeaturePayload) -> Response:
        response = Response()
        try:
            map_template: dict[str, int] = {}
            if schema.template_uids:
                templates = await query(
                    db=self.db,
                    table=DfEnginePromptTemplates,
                    columns=(DfEnginePromptTemplates.id, DfEnginePromptTemplates.uid),  # type: ignore
                    filters=(DfEnginePromptTemplates.uid.in_(schema.template_uids),),  # type: ignore
                )
                map_template = {uid: id_ for id_, uid in templates}
                if len(map_template) != len(schema.template_uids):
                    raise DataValidationError(
                        message="feature_template_not_found",
                        error={
                            f"template_uids.{idx}": ["prompt_template_not_found"]
                            for idx, uid in enumerate(schema.template_uids)
                            if uid not in map_template
                        },
                    )

            feature = DfEngineFeatures(
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
                        feature_id=feature.id,
                        template_id=template_id,
                    )
                )
            await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} created feature uid={feature.uid} "
                f"name={feature.name!r} is_active={feature.is_active} template_count={len(map_template)}"
            )

            new_record = self.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEngineFeatures,
                        options=self.options(),
                        filters=(DfEngineFeatures.uid == str(feature.uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )
            await set_json(
                self.redis,
                self.detail_cache_key(feature.uid),  # type: ignore
                new_record,
                ttl=CACHE_TTL_SECONDS,
            )

            list_cache_key = self.list_cache_key()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [new_record, *cached_list]
                logging.info(
                    f"user={self.user['user_id']} appended feature uid={feature.uid} to list cache count={len(records)}"
                )
            else:
                records = await self.rebuild_response()

            await set_json(self.redis, list_cache_key, records, ttl=CACHE_TTL_SECONDS)
            response.data = records
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
            "is linked, and unchanged ones keep their existing mapping row (not deleted "
            "and recreated). It has no minimum length — pass an empty list to unlink every "
            "template. Every uid must reference an existing prompt template or the request "
            "fails with a 422. `name` must remain unique across all existing features. The "
            "record's `updated_by` is taken from the authenticated user resolved from the "
            "bearer token, not from the request body. Deactivating a feature (`is_active` = "
            "`false`) keeps it in the list, flagged inactive, and does not touch its "
            "template or menu links. Returns the full, up-to-date list of features."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
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
            map_template: dict[str, int] = {}
            if schema.template_uids:
                templates = await query(
                    db=self.db,
                    table=DfEnginePromptTemplates,
                    columns=(DfEnginePromptTemplates.id, DfEnginePromptTemplates.uid),  # type: ignore
                    filters=(DfEnginePromptTemplates.uid.in_(schema.template_uids),),  # type: ignore
                )
                map_template = {uid: id_ for id_, uid in templates}
                if len(map_template) != len(schema.template_uids):
                    raise DataValidationError(
                        message="feature_template_not_found",
                        error={
                            f"template_uids.{idx}": ["prompt_template_not_found"]
                            for idx, uid in enumerate(schema.template_uids)
                            if uid not in map_template
                        },
                    )

            feature = await query(
                db=self.db,
                table=DfEngineFeatures,
                options=self.options(),
                filters=(DfEngineFeatures.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if feature is None:
                raise DataNotFoundError(message="feature_not_found")

            feature.name = schema.name
            feature.description = schema.description
            feature.is_active = schema.is_active
            feature.updated_by = int(self.user["user_id"])
            feature.updated_at = local_time()

            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="feature_already_exists")

            desired_ids = set(map_template.values())

            existing_mappings = await query(
                db=self.db,
                table=DfEngineFeaturePromptMappings,
                filters=(DfEngineFeaturePromptMappings.feature_id == feature.id,),  # type: ignore
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

            self.db.expire(feature)
            updated_feature = self.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEngineFeatures,
                        options=self.options(),
                        filters=(DfEngineFeatures.uid == str(uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )

            await set_json(
                self.redis,
                self.detail_cache_key(uid),
                updated_feature,
                ttl=CACHE_TTL_SECONDS,
            )

            list_cache_key = self.list_cache_key()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [updated_feature if r["uid"] == str(uid) else r for r in cached_list]
                logging.info(
                    f"user={self.user['user_id']} updated feature uid={uid} in list cache count={len(records)}"
                )
            else:
                records = await self.rebuild_response()

            await set_json(self.redis, list_cache_key, records, ttl=CACHE_TTL_SECONDS)
            response.data = records
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
            "`df_engine_feature_prompt_mappings` row linking it to a prompt template — "
            "there's no separate unlink step for templates. Fails with a 409 conflict if "
            "the feature is still linked to a menu by a `df_engine_menu_feature_mappings` "
            "row (i.e. `action.can_delete` is `false`) — unmap it in menu management "
            "first. 404s if no feature matches `uid`. Returns the full, up-to-date list of "
            "remaining features."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
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
            feature = await query(
                db=self.db,
                table=DfEngineFeatures,
                options=self.options(),
                filters=(DfEngineFeatures.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if feature is None:
                raise DataNotFoundError(message="feature_not_found")

            formatted_feature = self.format(serialize(feature))
            if formatted_feature.get("action", {}).get("can_delete", False) is False:
                raise DataConflictError(message="feature_in_use")

            await self.db.execute(
                delete(DfEngineFeaturePromptMappings).where(
                    DfEngineFeaturePromptMappings.feature_id == feature.id  # type: ignore
                )
            )
            await self.db.delete(feature)
            await self.db.flush()

            logging.info(f"user={self.user['user_id']} deleted feature uid={feature.uid} name={feature.name!r}")

            await self.redis.delete(self.detail_cache_key(uid))

            list_cache_key = self.list_cache_key()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [r for r in cached_list if r["uid"] != str(uid)]
                logging.info(
                    f"user={self.user['user_id']} removed feature uid={uid} from list cache count={len(records)}"
                )
            else:
                records = await self.rebuild_response()

            await set_json(self.redis, list_cache_key, records, ttl=CACHE_TTL_SECONDS)
            response.data = records
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
