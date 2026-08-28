from typing import Any
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from services.mysql import query
from services.mysql.model import (
    DfEngineFeaturePromptMappings,
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEnginePromptTemplates,
    Users,
    Employees,
)
from log import logging
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees


class FeatureManagementService:
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
            "can_fetch_detail": "fetch_df_engine_features" in user_permissions,
            "can_update": "update_df_engine_feature" in user_permissions,
            "can_delete": "delete_df_engine_feature" in user_permissions
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

    async def rebuild_response(self, db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
        """Full, newest-first feature list from the DB — used to repopulate the
        `:all` cache whenever a write finds it cold."""
        results = await query(
            db=db,
            table=DfEngineFeatures,
            options=self.options(),
            order_by=(DfEngineFeatures.created_at.desc(),),  # type: ignore
        )
        records = [self.format(record) for record in serialize(results)]
        logging.info(f"user={user_id} rebuilt feature list cache count={len(records)}")
        return records
