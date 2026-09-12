import traceback
from typing import Optional
from uuid import UUID
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import delete
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.menu_management import MenuPayload
from services.mysql import query
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
)
from services.redis import get_json, set_json, CacheKeys
from services.menu_management import MenuManagementService
from log import logging
from error import ServiceError, BaseError, DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize


menu_management_service = MenuManagementService()


class MenuManagementController(CoreDependencies):
    @controller.get(
        "/menu-management",
        summary="List or search menus.",
        description=(
            "Shows all menus, newest first, including both active and inactive ones. "
            "Type text into `name` to search for a menu by its name. Each menu also "
            "lists the features linked to it, plus who created and last updated it, "
            "and what actions the current user is allowed to do."
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
        cache_key = CacheKeys()
        try:
            menu_manegement_global_cache_key = cache_key.menu_managements(name)
            cached_menu_management_global = await get_json(self.redis, menu_manegement_global_cache_key)
            if cached_menu_management_global:
                logging.info(
                    f"user={self.user['user_id']} listed menus source=cache name={name!r} count={len(cached_menu_management_global)}"
                )
                response.data = cached_menu_management_global
                return response

            results = await query(
                db=self.db,
                table=DfEngineMenus,
                options=menu_management_service.options(),
                filters=(DfEngineMenus.name.ilike(f"{name}%"),) if name else None,  # type: ignore
                order_by=(DfEngineMenus.created_at.desc(),),  # type: ignore
            )
            records = [menu_management_service.format(record) for record in serialize(results)]
            await set_json(self.redis, menu_manegement_global_cache_key, records)

            logging.info(f"user={self.user['user_id']} listed menus source=db name={name!r} count={len(records)}")
            response.data = records
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/menu-management/options",
        summary="List menu type options.",
        description=(
            "Shows the menu types you can pick from when creating or editing a menu. "
            "A type already used by another menu is marked unavailable, since each "
            "type can only belong to one menu at a time."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
    )
    async def menu_management_to_fetch_options(self) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            options_cache_key = cache_key.menu_management_options()
            cached_options = await get_json(self.redis, options_cache_key)
            if cached_options is not None:
                response.data = cached_options
                return response

            options = await menu_management_service.fetch_type_options(self.db)

            used_types = set(await query(db=self.db, table=DfEngineMenus, columns=(DfEngineMenus.type,)))  # type: ignore

            records = [{"type": option, "action": {"can_set_menu": option not in used_types}} for option in options]
            await set_json(self.redis, options_cache_key, records)
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
            "Shows the full details of one menu, including its linked features, who "
            "created and last updated it, and what the current user can do with it. "
            "Returns a not-found error if the menu doesn't exist."
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
        cache_key = CacheKeys()
        try:
            menu_manegement_global_cache_key = cache_key.menu_managements()
            cached_menu_management_global = await get_json(self.redis, menu_manegement_global_cache_key)
            if cached_menu_management_global:
                menu = None
                for record in cached_menu_management_global:
                    if record["uid"] == str(uid):
                        menu = record

                if not menu:
                    raise DataNotFoundError(message="menu_not_found")

                logging.info(f"user={self.user['user_id']} fetched menu uid={uid} source=list_cache")
                response.data = menu
                return response

            menu_managment_detail_cache_key = cache_key.menu_management_detail(uid)
            cached_menu_management_detail = await get_json(self.redis, menu_managment_detail_cache_key)
            if cached_menu_management_detail:
                logging.info(f"user={self.user['user_id']} fetched menu uid={uid} source=detail_cache")
                response.data = cached_menu_management_detail
                return response

            result = await query(
                db=self.db,
                table=DfEngineMenus,
                options=menu_management_service.options(),
                filters=(DfEngineMenus.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )

            if result is None:
                raise DataNotFoundError(message="menu_not_found")

            serialized_record = serialize(result)
            formatted_response = menu_management_service.format(serialized_record)
            await set_json(self.redis, menu_managment_detail_cache_key, formatted_response)

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
            "Creates a new menu and, at the same time, links it to any features you "
            "list in `feature_uids`. Every feature you list must already exist, "
            "otherwise the request is rejected and you're told which ones weren't "
            "found. You can also leave `feature_uids` empty to create a menu with no "
            "features yet and link them later. The menu name must be unique — you "
            "can't reuse a name that's already taken. Returns the full, up-to-date "
            "list of menus."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
    )
    async def menu_management_to_create_menu(self, schema: MenuPayload) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            await menu_management_service.validate_type(self.db, schema.type)

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

            await menu_management_service.validate_uniqueness(self.db, schema.name, schema.type)

            menu = DfEngineMenus(
                name=schema.name,
                type=schema.type,
                description=schema.description,
                is_active=schema.is_active,
                created_by=int(self.user["user_id"]),
            )
            self.db.add(menu)
            await self.db.flush()

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

            new_record = menu_management_service.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEngineMenus,
                        options=menu_management_service.options(),
                        filters=(DfEngineMenus.uid == str(menu.uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )
            await set_json(
                self.redis,
                cache_key.menu_management_detail(menu.uid),  # type: ignore
                new_record,
            )
            await self.redis.delete(cache_key.menu_management_options())

            list_cache_key = cache_key.menu_managements()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [new_record, *cached_list]
                logging.info(
                    f"user={self.user['user_id']} appended menu uid={menu.uid} to list cache count={len(records)}"
                )
            else:
                records = await menu_management_service.rebuild_response(self.db, self.user["user_id"])

            await set_json(self.redis, list_cache_key, records)
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
            "Updates a menu's details. Send the full menu information each time — "
            "not just the fields that changed. `feature_uids` should be the complete "
            "list of features this menu should have going forward: anything you leave "
            "out gets unlinked, anything new gets linked, and unchanged features stay "
            "as they are. You can pass an empty list to remove all linked features. "
            "Every feature you list must already exist. The menu name must stay "
            "unique. Turning a menu off (`is_active` = false) just hides it from "
            "active use — it stays in the list and keeps its linked features. Returns "
            "the full, up-to-date list of menus."
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
        cache_key = CacheKeys()
        try:
            await menu_management_service.validate_type(self.db, schema.type)

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
                options=menu_management_service.options(),
                filters=(DfEngineMenus.uid == str(uid),),  # type: ignore
                fetch_one=True,
            )
            if menu is None:
                raise DataNotFoundError(message="menu_not_found")

            await menu_management_service.validate_uniqueness(self.db, schema.name, schema.type, exclude_uid=str(uid))

            menu.name = schema.name
            menu.type = schema.type
            menu.description = schema.description
            menu.is_active = schema.is_active
            menu.updated_by = int(self.user["user_id"])
            menu.updated_at = local_time()
            await self.db.flush()

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
            updated_menu = menu_management_service.format(
                serialize(
                    await query(
                        db=self.db,
                        table=DfEngineMenus,
                        options=menu_management_service.options(),
                        filters=(DfEngineMenus.uid == str(uid),),  # type: ignore
                        fetch_one=True,
                    )
                )
            )

            await set_json(
                self.redis,
                cache_key.menu_management_detail(uid),
                updated_menu,
            )
            await self.redis.delete(cache_key.menu_management_options())

            list_cache_key = cache_key.menu_managements()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [updated_menu if r["uid"] == str(uid) else r for r in cached_list]
                logging.info(f"user={self.user['user_id']} updated menu uid={uid} in list cache count={len(records)}")
            else:
                records = await menu_management_service.rebuild_response(self.db, self.user["user_id"])

            await set_json(self.redis, list_cache_key, records)
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
            "Permanently deletes a menu and removes all of its links to features — "
            "you don't need to unlink features first. Returns a not-found error if "
            "the menu doesn't exist. Returns the full, up-to-date list of the "
            "remaining menus."
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
        cache_key = CacheKeys()
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

            await self.redis.delete(cache_key.menu_management_detail(uid))
            await self.redis.delete(cache_key.menu_management_options())

            list_cache_key = cache_key.menu_managements()
            cached_list = await get_json(self.redis, list_cache_key)
            if cached_list is not None:
                records = [r for r in cached_list if r["uid"] != str(uid)]
                logging.info(f"user={self.user['user_id']} removed menu uid={uid} from list cache count={len(records)}")
            else:
                records = await menu_management_service.rebuild_response(self.db, self.user["user_id"])

            await set_json(self.redis, list_cache_key, records)
            response.data = records
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
