import json
from typing import Any, Optional
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from services.mysql import query
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    DfEngineSettings,
    Users,
    Employees,
)
from error import ServiceError, DataNotFoundError, DataConflictError
from log import logging
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees

MENU_OPTIONS_SETTING_KEY = "menu_management_options"


class MenuManagementService:
    async def fetch_type_options(self, db: AsyncSession) -> list[str]:
        setting = await query(
            db=db,
            table=DfEngineSettings,
            filters=(DfEngineSettings.key == MENU_OPTIONS_SETTING_KEY,),  # type: ignore
            fetch_one=True,
        )
        return json.loads(setting.value) if setting and setting.value else []

    async def validate_type(self, db: AsyncSession, type_value: str) -> None:
        """`type` must be one of the option values from df_engine_settings
        (key=menu_management_options) — that setting is the single source of
        truth for valid menu types."""
        options = await self.fetch_type_options(db)
        if not options:
            raise ServiceError(message="menu_type_options_not_configured")
        if type_value not in options:
            raise DataNotFoundError(message="menu_type_not_found")

    async def validate_uniqueness(
        self, db: AsyncSession, name: str, type_value: str, exclude_uid: Optional[str] = None
    ) -> None:
        """`name` and `type` are each unique on `df_engine_menus`. Checked up
        front (rather than relying on the DB's IntegrityError) so a conflict
        on `type` isn't reported as a name conflict, or vice versa."""
        filters = (or_(DfEngineMenus.name == name, DfEngineMenus.type == type_value),)  # type: ignore
        if exclude_uid:
            filters = (*filters, DfEngineMenus.uid != exclude_uid)  # type: ignore
        conflicts = await query(db=db, table=DfEngineMenus, filters=filters)
        for menu in conflicts:
            if menu.type == type_value:
                raise DataConflictError(message="menu_type_already_in_use")
            if menu.name == name:
                raise DataConflictError(message="menu_already_exists")

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
                    "type": feature.get("type"),
                    "description": feature.get("description"),
                    "is_active": feature.get("is_active"),
                    "creator": format_user_employees(feature.get("created_by_user")),
                    "updater": format_user_employees(feature.get("updated_by_user")),
                }
            )
        record["features"] = features
        record["action"] = {
            "can_fetch_detail": "fetch_df_engine_menus" in user_permissions,
            "can_update": "update_df_engine_menu" in user_permissions,
            "can_delete": "delete_df_engine_menu" in user_permissions,
        }

        record.pop("id", None)
        record.pop("created_by_user", None)
        record.pop("updated_by_user", None)
        record.pop("created_by", None)
        record.pop("updated_by", None)
        record.pop("df_engine_menu_feature_mappings", None)
        return record

    async def rebuild_response(self, db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
        """Full, newest-first menu list from the DB — used to repopulate the
        `:all` cache whenever a write finds it cold."""
        results = await query(
            db=db,
            table=DfEngineMenus,
            options=self.options(),
            order_by=(DfEngineMenus.created_at.desc(),),  # type: ignore
        )
        records = [self.format(record) for record in serialize(results)]
        logging.info(f"user={user_id} rebuilt menu list cache count={len(records)}")
        return records
