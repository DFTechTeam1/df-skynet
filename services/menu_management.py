from typing import Any
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from services.mysql import query
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    Users,
    Employees,
)
from log import logging
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees


class MenuManagementService:
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
