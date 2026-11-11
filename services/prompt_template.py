import re
from typing import Any, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import selectinload, load_only
from services.mysql.model import (
    DfEnginePromptTemplates,
    DfEnginePromptTemplateReferences,
    DfEngineFeaturePromptMappings,
    Users,
    Employees,
)
from services.mysql import query
from log import logging
from error import DataNotFoundError, DataValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees


class PromptTemplateService:
    def options(self):
        """
        Define eager-loading options for prompt template queries.

        Loads only the fields required to build the API response:

        - Creator:
            - User image
            - Employee nickname
        - Updater:
            - User image
            - Employee nickname
        - Feature prompt mappings:
            - Mapping ID, used to determine whether the template
            can be safely deleted.

        Using `selectinload` prevents unnecessary lazy-loading queries
        and helps avoid N+1 query problems when fetching multiple
        prompt templates.

        Returns:
            tuple: SQLAlchemy relationship loading options.
        """
        return (
            selectinload(DfEnginePromptTemplates.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEnginePromptTemplates.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(  # type: ignore
                DfEnginePromptTemplates.df_engine_feature_prompt_mappings  # type: ignore
            ).load_only(
                DfEngineFeaturePromptMappings.id  # type: ignore
            ),
            # Referenced templates, returned as `template_references` (uid + name).
            selectinload(DfEnginePromptTemplates.template_references)  # type: ignore
            .selectinload(DfEnginePromptTemplateReferences.reference)  # type: ignore
            .load_only(DfEnginePromptTemplates.uid, DfEnginePromptTemplates.name),  # type: ignore
        )

    def format(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Format a prompt template database record for API responses.

        This method transforms raw database data into the response
        structure expected by the client. It handles:

        - Datetime formatting.
        - Creator and updater formatting.
        - User permission-based action availability.
        - Delete restrictions for templates currently in use.
        - Removal of internal database fields.

        Args:
            record: Serialized prompt template database record.

        Returns:
            dict[str, Any]: Formatted prompt template response.
        """

        user_permissions = [
            "delete_df_engine_prompt_template",
            "fetch_df_engine_prompt_templates",
            "update_df_engine_prompt_template",
        ]
        record["created_at"] = format_datetime(record["created_at"])
        record["updated_at"] = format_datetime(record["updated_at"])
        record["creator"] = format_user_employees(record["created_by_user"])
        record["updater"] = format_user_employees(record["updated_by_user"])

        # Referenced templates; skip any row whose template is gone.
        record["template_references"] = [
            {"uid": ref["reference"]["uid"], "name": ref["reference"]["name"]}
            for ref in record.get("template_references", [])
            if ref.get("reference")
        ]
        record["action"] = {
            "can_fetch_detail": "fetch_df_engine_prompt_templates" in user_permissions,
            "can_delete": (
                "delete_df_engine_prompt_template" in user_permissions
                and not record["df_engine_feature_prompt_mappings"]
            ),
            "can_update": "update_df_engine_prompt_template" in user_permissions,
        }
        record.pop("id", None)
        record.pop("created_by_user", None)
        record.pop("updated_by_user", None)
        record.pop("created_by", None)
        record.pop("updated_by", None)
        record.pop("df_engine_feature_prompt_mappings", None)

        return record

    async def rebuild_response(self, db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
        """
        Rebuild the complete prompt template list from the database.

        This method is used to repopulate the `:all` cache when the
        cache is missing or needs to be rebuilt after a write operation.

        Templates are returned in newest-first order based on
        `created_at`.

        Processing flow:

            Database query
                ↓
            Eager-load required relationships
                ↓
            Serialize database records
                ↓
            Format each record
                ↓
            Return API-ready records

        Returns:
            list[dict[str, Any]]: Formatted prompt template records,
            ordered from newest to oldest.
        """

        results = await query(
            db=db,
            table=DfEnginePromptTemplates,
            options=self.options(),
            order_by=(
                DfEnginePromptTemplates.created_at.desc(),  # type: ignore
            ),
        )

        records = [self.format(record) for record in serialize(results)]
        logging.info(f"user={user_id} rebuilt prompt template list cache count={len(records)}")

        return records

    async def resolve_reference_ids(
        self, db: AsyncSession, uids: list[UUID], own_uid: Optional[UUID] = None
    ) -> list[int]:
        """Map referenced template UIDs to ids, rejecting self-references and unknown UIDs."""
        if not uids:
            return []
        if own_uid is not None and own_uid in uids:
            raise DataValidationError(
                message="prompt_template_self_reference",
                error={"template_references": ["prompt_template_self_reference"]},
            )
        rows = (
            await db.execute(
                select(DfEnginePromptTemplates.id, DfEnginePromptTemplates.uid).where(
                    DfEnginePromptTemplates.uid.in_([str(u) for u in uids])  # type: ignore
                )
            )
        ).all()
        id_by_uid = {row.uid: row.id for row in rows}
        missing = [str(u) for u in uids if str(u) not in id_by_uid]
        if missing:
            raise DataNotFoundError(
                message="prompt_template_not_found",
                error={"template_references": ["prompt_template_not_found"]},
            )
        return [id_by_uid[str(u)] for u in uids]

    def format_prompt(self, prompt: str, uids: list[UUID]) -> str:
        """Rewrite each referenced UID in the prompt as `<refer to UID>`; payload guarantees each is present."""
        for u in uids:
            # Lookbehind keeps already-formatted tags (e.g. a re-sent stored prompt) from double-wrapping.
            prompt = re.sub(rf"(?<!<refer to ){re.escape(str(u))}", f"<refer to {u}>", prompt)
        return prompt
