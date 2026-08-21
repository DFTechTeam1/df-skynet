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
from schemas.payload.menu_management import MenuPayload
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    Users,
    Employees,
)
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees
# from apps.dependency.permission import require_permissions


menu_permission = {
    "fetch_df_engine_menus": "fetch_df_engine_menus",
    "update_df_engine_menu": "update_df_engine_menu",
    "delete_df_engine_menu": "delete_df_engine_menu",
}


class MenuManagementController(CoreDependencies):
    def query_options(self):
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

    def format_response(self, menu: dict[str, Any], permissions: list[str]) -> dict[str, Any]:
        menu["created_at"] = format_datetime(menu["created_at"])
        menu["updated_at"] = format_datetime(menu["updated_at"])
        menu["creator"] = format_user_employees(menu["created_by_user"])
        menu["updater"] = format_user_employees(menu["updated_by_user"])

        features = []
        for mapping in menu.get("df_engine_menu_feature_mappings", []):
            feature = mapping.get("df_engine_features", {})
            if not feature.get("is_active"):
                continue
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
        menu["features"] = features
        menu["action"] = {
            "can_fetch_detail": menu_permission["fetch_df_engine_menus"] in permissions,
            "can_update_menu": menu_permission["update_df_engine_menu"] in permissions,
            "can_delete_menu": menu_permission["delete_df_engine_menu"] in permissions,
        }

        menu.pop("id", None)
        menu.pop("created_by_user", None)
        menu.pop("updated_by_user", None)
        menu.pop("created_by", None)
        menu.pop("updated_by", None)
        menu.pop("df_engine_menu_feature_mappings", None)
        return menu

    async def get_menus(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """Will fetch all menus available if name not provided, ordered by latest to oldest."""
        query = select(DfEngineMenus)
        if name:
            query = query.where(DfEngineMenus.name.ilike(f"{name}%"))  # type: ignore
        records = (
            (
                await self.db.execute(
                    query.options(*self.query_options()).order_by(  # type: ignore
                        DfEngineMenus.created_at.desc()  # type: ignore
                    )
                )
            )
            .scalars()
            .all()
        )

        permissions = self.user.get("permissions", [])
        return [self.format_response(menu, permissions) for menu in serialize(records)]

    async def get_menu_detail(self, uid: UUID) -> dict[str, Any]:
        record = (
            await self.db.execute(
                select(DfEngineMenus)
                .where(DfEngineMenus.uid == str(uid))  # type: ignore
                .options(*self.query_options())  # type: ignore
            )
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="menu_not_found")

        permissions = self.user.get("permissions", [])
        return self.format_response(serialize(record), permissions)

    async def get_menu(self, uid: UUID) -> DfEngineMenus:
        record = (
            await self.db.execute(
                select(DfEngineMenus).where(DfEngineMenus.uid == str(uid))  # type: ignore
            )
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="menu_not_found")
        return record

    async def get_features_by_uid(self, feature_uids: list[str]) -> dict[str, int]:
        if not feature_uids:
            return {}

        features = (
            await self.db.execute(
                select(DfEngineFeatures.id, DfEngineFeatures.uid).where(  # type: ignore
                    DfEngineFeatures.uid.in_(feature_uids)  # type: ignore
                )
            )
        ).all()
        map_feature: dict[str, int] = {uid: id_ for id_, uid in features}

        if len(map_feature) != len(feature_uids):
            error = {
                f"feature_uids.{idx}": ["feature_not_found"]
                for idx, feature_uid in enumerate(feature_uids)
                if feature_uid not in map_feature
            }
            raise DataValidationError(message="menu_feature_not_found", error=error)

        return map_feature

    @controller.get(
        "/menu-management",
        summary="List or search menus.",
        description=(
            "Returns menus (`df_engine_menus` rows), newest first — both active and "
            "inactive, since this screen manages and toggles inactive menus too. Pass "
            "`name` to search — only menus whose name contains that text "
            "(case-insensitive) are returned, in the exact same shape as the unfiltered "
            "list. Each menu includes a nested `features` array built from "
            "`df_engine_menu_feature_mappings`, filtered to active features only (inactive "
            "ones are still mapped internally but omitted from this array) — one menu can "
            "list many features, and the same feature can appear under many different "
            "menus. Each menu also includes its resolved `creator` / `updater` and an "
            "`action` block reflecting which menu-management actions the current user is "
            "permitted to perform."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_menus"])) # Will be enabled later
        # ]
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
            response.data = await self.get_menus(name=name)
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
        # dependencies=[
        #     Depends(require_permissions(["fetch_menus"])) # Will be enabled later
        # ]
    )
    async def menu_management_with_uid_to_fetch_detail_menus(
        self,
        uid: UUID = Path(
            description="Menu UID.",
            examples=["36c101d8-12a8-4e3c-bf3d-eb49a337abdd"],
        ),
    ) -> Response:
        response = Response()
        try:
            response.data = await self.get_menu_detail(uid)
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
            "to the features given in `feature_uids` — every uid must reference an "
            "existing feature, or the whole request fails. `feature_uids` has no minimum "
            "length: omit it (or pass an empty list) to create a menu with no linked "
            "feature yet, or pass one or many to wire them up immediately. `name` must be "
            "unique across all existing menus. The record's `created_by` is taken from the "
            "authenticated user resolved from the bearer token, not from the request body. "
            "Returns the full, up-to-date list of menus, so the frontend can refresh its "
            "list without a separate re-fetch."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["create_menu"])) # Will be enabled later
        # ]
    )
    async def menu_management_to_create_menu(self, schema: MenuPayload) -> Response:
        response = Response()
        try:
            map_feature = await self.get_features_by_uid(schema.feature_uids)

            menu = DfEngineMenus(
                uid=str(uuid4()),
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
                        uid=str(uuid4()),
                        menu_id=menu.id,
                        feature_id=feature_id,
                    )
                )
            await self.db.flush()

            response.data = await self.get_menus()
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
            "linked, and unchanged ones are left untouched (their `mapping_uid` is "
            "preserved). It has no minimum length — pass an empty list to unlink every "
            "feature from the menu. `name` must remain unique across all existing menus. "
            "The record's `updated_by` is taken from the authenticated user resolved from "
            "the bearer token, not from the request body. Setting `is_active` to `false` "
            "also removes every `df_engine_menu_feature_mappings` row linking this menu to "
            "a feature. Returns the full, up-to-date list of menus."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["update_menu"])) # Will be enabled later
        # ]
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
            menu = await self.get_menu(uid)
            map_feature = await self.get_features_by_uid(schema.feature_uids)

            menu.name = schema.name
            menu.description = schema.description
            menu.is_active = schema.is_active
            menu.updated_by = int(self.user["user_id"])

            if not schema.is_active:
                await self.db.execute(
                    delete(DfEngineMenuFeatureMappings).where(
                        DfEngineMenuFeatureMappings.menu_id == menu.id  # type: ignore
                    )
                )

            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="menu_already_exists")

            # An inactive menu keeps no feature mappings, regardless of what
            # feature_uids was passed — otherwise the diff below would just
            # re-create what the cascade-delete above just removed.
            desired_ids = set(map_feature.values()) if schema.is_active else set()

            existing_mappings = (
                (
                    await self.db.execute(
                        select(DfEngineMenuFeatureMappings).where(
                            DfEngineMenuFeatureMappings.menu_id == menu.id  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_by_feature_id = {mapping.feature_id: mapping for mapping in existing_mappings}

            for feature_id, mapping in existing_by_feature_id.items():
                if feature_id not in desired_ids:
                    await self.db.delete(mapping)

            for feature_id in desired_ids:
                if feature_id not in existing_by_feature_id:
                    self.db.add(
                        DfEngineMenuFeatureMappings(
                            uid=str(uuid4()),
                            menu_id=menu.id,
                            feature_id=feature_id,
                        )
                    )

            await self.db.flush()

            response.data = await self.get_menus()
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
            "separate unlink step, deleting a menu removes it entirely. Returns the full, "
            "up-to-date list of remaining menus."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Menu Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["delete_menu"])) # Will be enabled later
        # ]
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
            menu = await self.get_menu(uid)

            mappings = (
                (
                    await self.db.execute(
                        select(DfEngineMenuFeatureMappings).where(
                            DfEngineMenuFeatureMappings.menu_id == menu.id  # type: ignore
                        )
                    )
                )
                .scalars()
                .all()
            )
            for mapping in mappings:
                await self.db.delete(mapping)

            await self.db.delete(menu)
            await self.db.flush()

            response.data = await self.get_menus()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
