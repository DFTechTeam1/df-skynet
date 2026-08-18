from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class FeaturePayload(BaseModel):
    """Payload to create or fully replace a feature (`df_engine_actions` row).

    Used for both create and update — update replaces the full record, not a
    partial diff. `name` must be unique across all existing features.
    `template_uids` is the complete set of prompt templates linked to this
    feature: on update, any currently linked template missing from the list
    is unlinked, any new uid is linked, and unchanged ones are left alone.
    It has no minimum length — a feature may be created or left with zero
    linked templates, or with one or many, all in the same call.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique, human-readable name identifying this feature.",
        examples=["Enhance prompt"],
    )
    description: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Free-text explanation of what this feature does.",
        examples=["Rewrites and expands the user prompt with the enhancer model."],
    )
    is_active: bool = Field(
        default=True,
        description="Whether this feature is available to be assigned to pages.",
        examples=[True],
    )
    template_uids: list[str] = Field(
        default_factory=list,
        description=(
            "Full desired set of prompt template UIDs linked to this feature. Omit or pass an empty list for a feature with no linked templates."
        ),
        examples=[
            [
                "8d96ff4e-5c35-4329-bd5d-827e2c68599d",
                "5048ee4d-8259-4c2e-a9a1-1eee369ab0c1",
            ]
        ],
    )

    @field_validator("template_uids", mode="before")
    @classmethod
    def dedupe_template_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))
