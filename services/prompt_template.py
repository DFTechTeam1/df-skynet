from typing import Any
from sqlalchemy.orm import selectinload
from services.mysql.model import DfEnginePromptTemplates, DfEngineFeaturePromptMappings, Users, Employees
from services.mysql import query
from log import logging
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
            # Load the user who created the prompt template.
            # Only the user's image and employee nickname are required
            # for the formatted creator response.
            selectinload(DfEnginePromptTemplates.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            # Load the user who last updated the prompt template.
            # Only the user's image and employee nickname are required
            # for the formatted updater response.
            selectinload(DfEnginePromptTemplates.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            # Load feature prompt mappings only to determine whether
            # the prompt template is currently being used.
            #
            # The mapping data is not returned to the client and is
            # removed in `format()`.
            selectinload(  # type: ignore
                DfEnginePromptTemplates.df_engine_feature_prompt_mappings  # type: ignore
            ).load_only(
                DfEngineFeaturePromptMappings.id  # type: ignore
            ),
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

        # TODO:
        # Replace this temporary hard-coded permission list with the
        # authenticated user's actual permissions.
        user_permissions = [
            "delete_df_engine_prompt_template",
            "fetch_df_engine_prompt_templates",
            "update_df_engine_prompt_template",
        ]

        # Convert database datetime values into the standard
        # application/API datetime format.
        record["created_at"] = format_datetime(record["created_at"])
        record["updated_at"] = format_datetime(record["updated_at"])

        # Convert the raw creator and updater relationships into the
        # simplified user/employee representation expected by the API.
        record["creator"] = format_user_employees(record["created_by_user"])
        record["updater"] = format_user_employees(record["updated_by_user"])

        # Determine which actions are available for this template.
        #
        # `can_delete` has an additional restriction:
        # a template cannot be deleted when it is already mapped
        # to a DF Engine feature.
        record["action"] = {
            "can_fetch_detail": "fetch_df_engine_prompt_templates" in user_permissions,
            "can_delete": (
                "delete_df_engine_prompt_template" in user_permissions
                and not record["df_engine_feature_prompt_mappings"]
            ),
            "can_update": "update_df_engine_prompt_template" in user_permissions,
        }

        # Remove internal database fields that should not be exposed
        # in the API response.
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

        # Fetch all prompt templates using the eager-loading options
        # defined in `options()`.
        #
        # Templates are ordered by creation time in descending order
        # so the newest templates appear first.
        results = await query(
            db=db,
            table=DfEnginePromptTemplates,
            options=self.options(),
            order_by=(
                DfEnginePromptTemplates.created_at.desc(),  # type: ignore
            ),
        )

        # Serialize the database models and format each record into
        # the structure expected by the API/cache.
        records = [self.format(record) for record in serialize(results)]

        # Log cache rebuild information for debugging and monitoring.
        logging.info(f"user={user_id} rebuilt prompt template list cache count={len(records)}")

        return records
