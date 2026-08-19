from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class MenuPayload(BaseModel):
    """Payload to create or fully replace a menu (`df_engine_menus` row).

    Used for both create and update — update replaces the full record, not a
    partial diff. `name` must be unique across all existing menus.
    `feature_uids` is the complete set of features linked to this menu: on
    update, any currently linked feature missing from the list is unlinked,
    any new uid is linked, and unchanged ones are left alone. It has no
    minimum length — a menu may be created or left with zero linked
    features, or with one or many, all in the same call.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique, human-readable name identifying this menu.",
        examples=["Generate"],
    )
    description: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Free-text explanation of what this menu is for.",
        examples=["Main generation workspace."],
    )
    is_active: bool = Field(
        default=True,
        description="Whether this menu is visible to users.",
        examples=[True],
    )
    feature_uids: list[str] = Field(
        default_factory=list,
        description=(
            "Full desired set of feature UIDs linked to this menu. Omit or pass an empty list for a menu with no linked features."
        ),
        examples=[
            [
                "8d96ff4e-5c35-4329-bd5d-827e2c68599d",
                "5048ee4d-8259-4c2e-a9a1-1eee369ab0c1",
            ]
        ],
    )

    @field_validator("feature_uids", mode="before")
    @classmethod
    def dedupe_feature_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))
