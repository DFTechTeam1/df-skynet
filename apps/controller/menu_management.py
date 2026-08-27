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
from schemas.payload.menu_management import MenuPayload
from services.mysql import query
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    Users,
    Employees,
)
from services.redis import get_json, set_json
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees

menu_permission = {
    "fetch_df_engine_menus": "fetch_df_engine_menus",
    "update_df_engine_menu": "update_df_engine_menu",
    "delete_df_engine_menu": "delete_df_engine_menu",
}

CACHE_TTL_SECONDS = 3600


class MenuManagementController(CoreDependencies):
    def list_cache_key(self, name: Optional[str] = None) -> str:
        return f"menu_management:list:{(name or '').strip().lower() or 'all'}"

    def detail_cache_key(self, uid: UUID) -> str:
        return f"menu_management:detail:{uid}"

    def options(self):
        return (
            selectinload(DfEngineMenus.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineMenus.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(  # type: ignore
                DfEngineMenus.df_engine_menu_feature_mappings  # type: ignore
            )
            .selectinload(DfEngineMenuFeatureMappings.df_engine_features)  # type: ignore
            .selectinload(DfEngineFeatures.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineMenus.df_engine_menu_feature_mappings)  # type: ignore
            .selectinload(DfEngineMenuFeatureMappings.df_engine_features)  # type: ignore
            .selectinload(DfEngineFeatures.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        )

    def format(self, record: dict[str, Any]) -> dict[str, Any]:
        user_permissions = [
            "fetch_df_engine_menus",
            "update_df_engine_menu",
            "delete_df_engine_menu",
        ]  # will be overriden first later will be using actual user permissions

        record["created_at"] = format_datetime(record["created_at"])
        record["updated_at"] = format_datetime(record["updated_at"])
        record["creator"] = format_user_employees(record["created_by_user"])
        record["updater"] = format_user_employees(record["updated_by_user"])

        features = []
        for mapping in record.get("df_engine_menu_feature_mappings", []):
            feature = mapping.get("df_engine_features", {})
            features.append(
                {
                    "created_at": format_datetime(feature.get("created_at")),
                    "updated_at": format_datetime(feature.get("updated_at")),
                    "feature_uid": feature.get("uid"),
                    "name": feature.get("name"),
                    "description": feature.get("description"),
                    "is_active": feature.get("is_active"),
                    "creator": format_user_employees(feature.get("created_by_user")),
                    "updater": format_user_employees(feature.get("updated_by_user")),
                }
            )
        record["features"] = features
        record["action"] = {
            "can_fetch_detail": menu_permission["fetch_df_engine_menus"] in user_permissions,
            "can_update": menu_permission["update_df_engine_menu"] in user_permissions,
            "can_delete": menu_permission["delete_df_engine_menu"] in user_permissions,
        }

        record.pop("id", None)
        record.pop("created_by_user", None)
        record.pop("updated_by_user", None)
        record.pop("created_by", None)
        record.pop("updated_by", None)
        record.pop("df_engine_menu_feature_mappings", None)
        return record

    async def rebuild_response(self) -> list[dict[str, Any]]:
        """Full, newest-first menu list from the DB — used to repopulate the
        `:all` cache whenever a write finds it cold."""
        results = await query(
            db=self.db,
            table=DfEngineMenus,
            options=self.options(),
            order_by=(DfEngineMenus.created_at.desc(),),  # type: ignore
        )
        records = [self.format(record) for record in serialize(results)]
        logging.info(f"user={self.user['user_id']} rebuilt menu list cache count={len(records)}")
        return records

    @controller.get(
        "/menu-management",
        summary="List or search menus.",
        description=(
            "Returns menus (`df_engine_menus` rows), newest first — both active and "
            "inactive, since this screen manages and toggles inactive menus too. Pass "
            "`name` to search — only menus whose name starts with that text "
            "(case-insensitive prefix match) are returned, in the exact same shape as the "
            "unfiltered list. Each menu includes a nested `features` array built from "
            "`df_engine_menu_feature_mappings` — every linked feature, active or inactive, "
            "each carrying its own `is_active` flag. One menu can list many features, and "
            "the same feature can be linked to many different menus. Each menu also "
            "includes its resolved `creator` / `updater` and an `action` block reflecting "
            "which menu-management actions the current user is permitted to perform."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
    )
    async def menu_management_to_fetch_menus(
        self,
        name: Optional[str] = Query(
            default=None,
            min_length=1,
            description="Search text to filter menus by name (case-insensitive, partial match). Omit to list all.",
            examples=["Generate"],
        ),
    ) -> Response:
        response = Response()
        try:
            list_cache_key = self.list_cache_key(name)
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list:
                logging.info(
                    f"user={self.user['user_id']} listed menus source=cache name={name!r} count={len(cached_list)}"
                )
                response.data = cached_list
                return response

            results = await query(
                db=self.db,
                table=DfEngineMenus,
                options=self.options(),
                filters=(DfEngineMenus.name.ilike(f"{name}%"),) if name else None,  # type: ignore
                order_by=(DfEngineMenus.created_at.desc(),),  # type: ignore
            )
            records = [self.format(record) for record in serialize(results)]
            await set_json(self.redis, list_cache_key, records, ttl=CACHE_TTL_SECONDS)

            logging.info(f"user={self.user['user_id']} listed menus source=db name={name!r} count={len(records)}")
            response.data = records
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/menu-management/{uid}",
        summary="Detail of a menu.",
        description=(
            "Returns a single menu (`df_engine_menus` row) identified by `uid`, in the "
            "exact same shape as one item from the list endpoint — including its nested "
            "`features` array, resolved `creator` / `updater`, and `action` block. 404s if "
            "no menu matches `uid`."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
    )
    async def menu_management_with_uid_to_fetch_detail_menu(
        self,
        uid: UUID = Path(
            description="Menu UID.",
            examples=["36c101d8-12a8-4e3c-bf3d-eb49a337abdd"],
        ),
    ) -> Response:
        response = Response()
        try:
            list_cache_key = self.list_cache_key()
            cached_global = await get_json(self.redis, list_cache_key)
            if cached_global:
                menu = None
                for record in cached_global:
                    if record["uid"] == str(uid):
                        menu = record

                if not menu:
                    raise DataNotFoundError(message="menu_not_found")

                logging.info(f"user={self.user['user_id']} fetched menu uid={uid} source=list_cache")
                response.data = menu
                return response

            detail_cache_key = self.detail_cache_key(uid)
            cached_detail = await get_json(self.redis, detail_cache_key)
            if cached_detail:
                logging.info(f"user={self.user['user_id']} fetched menu uid={uid} source=detail_cache")
                response.data = cached_detail
                return response

            result = await query(
                db=self.db,
                table=DfEngineMenus,
                options=self.options(),
                filters=(DfEngineMenus.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )

            if result is None:
                raise DataNotFoundError(message="menu_not_found")

            serialized_record = serialize(result)
            formatted_response = self.format(serialized_record)
            await set_json(self.redis, detail_cache_key, formatted_response, ttl=CACHE_TTL_SECONDS)

            logging.info(f"user={self.user['user_id']} fetched menu uid={uid} source=db")
            response.data = formatted_response
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/menu-management",
        summary="Create a menu.",
        description=(
            "Registers a new menu (`df_engine_menus` row) and, in the same call, links it "
            "to the features given in `feature_uids` — every uid must reference an existing "
            "feature, or the whole request fails with a 422 listing the offending indices. "
            "`feature_uids` has no minimum length: omit it (or pass an empty list) to "
            "create a menu with no linked feature yet, or pass one or many to wire them up "
            "immediately. `name` must be unique across all existing menus. The record's "
            "`created_by` is taken from the authenticated user resolved from the bearer "
            "token, not from the request body. Returns the full, up-to-date list of menus, "
            "so the frontend can refresh its list without a separate re-fetch."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
    )
    async def menu_management_to_create_menu(self, schema: MenuPayload) -> Response:
        response = Response()
        try:
            map_feature: dict[str, int] = {}
            if schema.feature_uids:
                features = await query(
                    db=self.db,
                    table=DfEngineFeatures,
                    columns=(DfEngineFeatures.id, DfEngineFeatures.uid),  # type: ignore
                    filters=(DfEngineFeatures.uid.in_(schema.feature_uids),),  # type: ignore
                )
                map_feature = {uid: id_ for id_, uid in features}
                if len(map_feature) != len(schema.feature_uids):
                    raise DataValidationError(
                        message="menu_feature_not_found",
                        error={
                            f"feature_uids.{idx}": ["feature_not_found"]
                            for idx, uid in enumerate(schema.feature_uids)
                            if uid not in map_feature
                        },
                    )

            menu = DfEngineMenus(
                name=schema.name,
                description=schema.description,
                is_active=schema.is_active,
                created_by=int(self.user["user_id"]),
            )
            self.db.add(menu)
            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="menu_already_exists")

            for feature_id in map_feature.values():
                self.db.add(
                    DfEngineMenuFeatureMappings(
                        menu_id=menu.id,
                        feature_id=feature_id,
                    )
                )
            await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} created menu uid={menu.uid} "
                f"name={menu.name!r} is_active={menu.is_active} feature_count={len(map_feature)}"
            )

            new_record = self.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEngineMenus,
                        options=self.options(),
                        filters=(DfEngineMenus.uid == str(menu.uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )
            await set_json(
                self.redis,
                self.detail_cache_key(menu.uid),  # type: ignore
                new_record,
                ttl=CACHE_TTL_SECONDS,
            )

            list_cache_key = self.list_cache_key()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [new_record, *cached_list]
                logging.info(
                    f"user={self.user['user_id']} appended menu uid={menu.uid} to list cache count={len(records)}"
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
        "/menu-management/{uid}",
        summary="Update a menu.",
        description=(
            "Replaces the menu identified by `uid` — the request body carries the full "
            "record (`name`, `description`, `is_active`, `feature_uids`), not a partial "
            "diff. `feature_uids` is the complete desired set of linked features: any "
            "currently linked feature missing from the list is unlinked, any new uid is "
            "linked, and unchanged ones keep their existing mapping row (not deleted and "
            "recreated). It has no minimum length — pass an empty list to unlink every "
            "feature. Every uid must reference an existing feature or the request fails "
            "with a 422. `name` must remain unique across all existing menus. The record's "
            "`updated_by` is taken from the authenticated user resolved from the bearer "
            "token, not from the request body. Deactivating a menu (`is_active` = `false`) "
            "keeps it in the list, flagged inactive, and does not touch its feature links. "
            "Returns the full, up-to-date list of menus."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
    )
    async def menu_management_to_update_menu(
        self,
        schema: MenuPayload,
        uid: UUID = Path(
            ...,
            description="Menu UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            map_feature: dict[str, int] = {}
            if schema.feature_uids:
                features = await query(
                    db=self.db,
                    table=DfEngineFeatures,
                    columns=(DfEngineFeatures.id, DfEngineFeatures.uid),  # type: ignore
                    filters=(DfEngineFeatures.uid.in_(schema.feature_uids),),  # type: ignore
                )
                map_feature = {uid: id_ for id_, uid in features}
                if len(map_feature) != len(schema.feature_uids):
                    raise DataValidationError(
                        message="menu_feature_not_found",
                        error={
                            f"feature_uids.{idx}": ["feature_not_found"]
                            for idx, uid in enumerate(schema.feature_uids)
                            if uid not in map_feature
                        },
                    )

            menu = await query(
                db=self.db,
                table=DfEngineMenus,
                options=self.options(),
                filters=(DfEngineMenus.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if menu is None:
                raise DataNotFoundError(message="menu_not_found")

            menu.name = schema.name
            menu.description = schema.description
            menu.is_active = schema.is_active
            menu.updated_by = int(self.user["user_id"])
            menu.updated_at = local_time()

            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="menu_already_exists")

            desired_ids = set(map_feature.values())

            existing_mappings = await query(
                db=self.db,
                table=DfEngineMenuFeatureMappings,
                filters=(DfEngineMenuFeatureMappings.menu_id == menu.id,),  # type: ignore
            )
            existing_by_feature_id = {mapping.feature_id: mapping for mapping in existing_mappings}
            unlinked_count = len(existing_by_feature_id.keys() - desired_ids)
            linked_count = len(desired_ids - existing_by_feature_id.keys())

            for feature_id, mapping in existing_by_feature_id.items():
                if feature_id not in desired_ids:
                    await self.db.delete(mapping)

            for feature_id in desired_ids:
                if feature_id not in existing_by_feature_id:
                    self.db.add(
                        DfEngineMenuFeatureMappings(
                            menu_id=menu.id,
                            feature_id=feature_id,
                        )
                    )

            await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} updated menu uid={menu.uid} "
                f"name={menu.name!r} is_active={menu.is_active} "
                f"features_linked={linked_count} features_unlinked={unlinked_count}"
            )

            self.db.expire(menu)
            updated_menu = self.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEngineMenus,
                        options=self.options(),
                        filters=(DfEngineMenus.uid == str(uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )

            await set_json(
                self.redis,
                self.detail_cache_key(uid),
                updated_menu,
                ttl=CACHE_TTL_SECONDS,
            )

            list_cache_key = self.list_cache_key()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [updated_menu if r["uid"] == str(uid) else r for r in cached_list]
                logging.info(f"user={self.user['user_id']} updated menu uid={uid} in list cache count={len(records)}")
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
        "/menu-management/{uid}",
        summary="Delete a menu.",
        description=(
            "Permanently deletes the menu identified by `uid`, along with every "
            "`df_engine_menu_feature_mappings` row linking it to a feature — there's no "
            "separate unlink step. 404s if no menu matches `uid`. Returns the full, "
            "up-to-date list of remaining menus."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
    )
    async def menu_management_to_delete_menu(
        self,
        uid: UUID = Path(
            ...,
            description="Menu UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            menu = await query(
                db=self.db,
                table=DfEngineMenus,
                filters=(DfEngineMenus.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if menu is None:
                raise DataNotFoundError(message="menu_not_found")

            await self.db.execute(
                delete(DfEngineMenuFeatureMappings).where(
                    DfEngineMenuFeatureMappings.menu_id == menu.id  # type: ignore
                )
            )
            await self.db.delete(menu)
            await self.db.flush()

            logging.info(f"user={self.user['user_id']} deleted menu uid={menu.uid} name={menu.name!r}")

            await self.redis.delete(self.detail_cache_key(uid))

            list_cache_key = self.list_cache_key()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [r for r in cached_list if r["uid"] != str(uid)]
                logging.info(f"user={self.user['user_id']} removed menu uid={uid} from list cache count={len(records)}")
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
