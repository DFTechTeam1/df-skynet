import traceback
from typing import Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.feature_management import FeaturePayload, FeatureTypes
from services.mysql import query
from services.mysql.model import (
    DfEngineFeaturePromptMappings,
    DfEngineFeatures,
    DfEnginePromptTemplates,
)
from services.redis import get_json, set_json, CacheKeys
from services.feature_management import FeatureManagementService
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize


feature_management_service = FeatureManagementService()


class FeatureManagementController(CoreDependencies):
    @controller.get(
        "/feature-management/types",
        summary="List feature types.",
        description="Returns all available feature type enum values used when creating or filtering features.",
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
    )
    async def feature_management_to_fetch_feature_types(self) -> Response:
        response = Response()
        try:
            feature_types = list(FeatureTypes)
            logging.info(f"user={self.user['user_id']} listed feature types count={len(feature_types)}")
            response.data = feature_types
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/feature-management",
        summary="List or search features.",
        description=(
            "Returns every feature, newest first, including inactive ones so they can be "
            "reactivated here. Pass `name` to search by feature name. Each feature shows "
            "its linked prompt templates, who created and last updated it, and what the "
            "current user is allowed to do with it."
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
        cache_key = CacheKeys()
        try:
            list_cache_key = cache_key.feature_managements(name)
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
                options=feature_management_service.options(),
                filters=(DfEngineFeatures.name.ilike(f"{name}%"),) if name else None,  # type: ignore
                order_by=(DfEngineFeatures.created_at.desc(),),  # type: ignore
            )
            records = [feature_management_service.format(record) for record in serialize(results)]
            await set_json(self.redis, list_cache_key, records)

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
            "Returns one feature's full details — the same information shown for it in the "
            "list, including its linked prompt templates. Fails if no feature matches the "
            "given ID."
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
        cache_key = CacheKeys()
        try:
            list_cache_key = cache_key.feature_managements()
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

            detail_cache_key = cache_key.feature_management_detail(uid)
            cached_detail = await get_json(self.redis, detail_cache_key)
            if cached_detail:
                logging.info(f"user={self.user['user_id']} fetched feature uid={uid} source=detail_cache")
                response.data = cached_detail
                return response

            result = await query(
                db=self.db,
                table=DfEngineFeatures,
                options=feature_management_service.options(),
                filters=(DfEngineFeatures.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )

            if result is None:
                raise DataNotFoundError(message="feature_not_found")

            serialized_record = serialize(result)
            formatted_response = feature_management_service.format(serialized_record)
            await set_json(self.redis, detail_cache_key, formatted_response)

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
            "Creates a new feature (image or video generation) and, optionally, links it to "
            "one or more prompt templates right away — every linked template must already "
            "exist. Feature names must be unique. Returns the full, up-to-date feature list."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Feature Management"],
        response_model=Response,
    )
    async def feature_management_to_create_feature(self, schema: FeaturePayload) -> Response:
        response = Response()
        cache_key = CacheKeys()
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
                type=schema.type.value,
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

            new_record = feature_management_service.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEngineFeatures,
                        options=feature_management_service.options(),
                        filters=(DfEngineFeatures.uid == str(feature.uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )
            await set_json(
                self.redis,
                cache_key.feature_management_detail(feature.uid),  # type: ignore
                new_record,
            )

            list_cache_key = cache_key.feature_managements()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [new_record, *cached_list]
                logging.info(
                    f"user={self.user['user_id']} appended feature uid={feature.uid} to list cache count={len(records)}"
                )
            else:
                records = await feature_management_service.rebuild_response(self.db, self.user["user_id"])

            await set_json(self.redis, list_cache_key, records)
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
            "Replaces a feature's full details, including its complete list of linked "
            "prompt templates — any template left out of the list gets unlinked, and any "
            "new one gets linked. Deactivating a feature keeps it in the list, just flagged "
            "as inactive. Returns the full, up-to-date feature list."
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
        cache_key = CacheKeys()
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
                options=feature_management_service.options(),
                filters=(DfEngineFeatures.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if feature is None:
                raise DataNotFoundError(message="feature_not_found")

            feature.name = schema.name
            feature.type = schema.type.value
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
            updated_feature = feature_management_service.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEngineFeatures,
                        options=feature_management_service.options(),
                        filters=(DfEngineFeatures.uid == str(uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )

            await set_json(
                self.redis,
                cache_key.feature_management_detail(uid),
                updated_feature,
            )

            list_cache_key = cache_key.feature_managements()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [updated_feature if r["uid"] == str(uid) else r for r in cached_list]
                logging.info(
                    f"user={self.user['user_id']} updated feature uid={uid} in list cache count={len(records)}"
                )
            else:
                records = await feature_management_service.rebuild_response(self.db, self.user["user_id"])

            await set_json(self.redis, list_cache_key, records)
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
            "Permanently deletes a feature and unlinks it from every prompt template. "
            "Blocked if the feature is still attached to a menu — remove it from that menu "
            "first. Returns the full, up-to-date list of remaining features."
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
        cache_key = CacheKeys()
        try:
            feature = await query(
                db=self.db,
                table=DfEngineFeatures,
                options=feature_management_service.options(),
                filters=(DfEngineFeatures.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if feature is None:
                raise DataNotFoundError(message="feature_not_found")

            formatted_feature = feature_management_service.format(serialize(feature))
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

            await self.redis.delete(cache_key.feature_management_detail(uid))

            list_cache_key = cache_key.feature_managements()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [r for r in cached_list if r["uid"] != str(uid)]
                logging.info(
                    f"user={self.user['user_id']} removed feature uid={uid} from list cache count={len(records)}"
                )
            else:
                records = await feature_management_service.rebuild_response(self.db, self.user["user_id"])

            await set_json(self.redis, list_cache_key, records)
            response.data = records
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
