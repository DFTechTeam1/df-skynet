from uuid import UUID
from typing import Optional
from pydantic import BaseModel, Field


class AdminView(BaseModel):
    """Controls whose assets show up in the Library for an admin."""

    see_all_asset: bool = Field(
        default=True,
        description=(
            "If true, the Library's admin view shows every user's assets, including "
            "private ones. If false, it shows only the viewing admin's own assets plus "
            "whatever's shared (Global / Role) — the same as a regular user sees."
        ),
    )


class UserRateLimit(BaseModel):
    """Per-minute request caps applied to every user."""

    generate_per_min: int = Field(
        default=0,
        ge=0,
        description="Max image/video generations a user can start per minute. 0 means no limit.",
    )
    enhance_per_min: int = Field(
        default=0,
        ge=0,
        description="Max prompt-enhance calls a user can make per minute. 0 means no limit.",
    )


class UserSpendCeiling(BaseModel):
    """Credit-spend caps, workspace-wide and per user."""

    daily_ceiling_global_user: int = Field(
        default=0,
        ge=0,
        description="Daily credit spend across all users combined before generation pauses workspace-wide. 0 means no cap.",
    )
    daily_ceiling_per_user: int = Field(
        default=0,
        ge=0,
        description="Daily credit spend a single user can make before they're blocked from further generation. 0 means no cap.",
    )


class UserComposeInput(BaseModel):
    """Limits on the free-text prompt a user types when composing a generation."""

    max_prompt_char: int = Field(
        default=4000,
        ge=1,
        description="Maximum character length of a user's compose/generation prompt. Longer input is rejected.",
    )


class UserStoryboard(BaseModel):
    """Limits on storyboard content — the per-scene script length, how many
    scenes a storyboard can hold, and how many shots a single scene can hold."""

    max_storyboard_char: int = Field(
        default=4000,
        ge=1,
        description="Maximum character length of a single storyboard scene's script/description. Longer input is rejected.",
    )
    max_scene_per_storyboard: int = Field(
        default=100,
        ge=1,
        description="Maximum number of scenes a single storyboard can contain.",
    )
    max_shot_per_scene: int = Field(
        default=100,
        ge=1,
        description="Maximum number of shots a single storyboard scene can contain.",
    )


class AdminSettingPayload(BaseModel):
    """Full DF Engine admin settings — every field must be supplied on save (not
    a partial diff), though each has a sensible default so the settings page can
    always submit a complete, valid payload."""

    admin_view: AdminView
    limit: UserRateLimit
    spend_ceiling: UserSpendCeiling
    storyboard: UserStoryboard
    compose_input: UserComposeInput
    enhancer_model: Optional[UUID] = Field(
        default=None,
        description="UID of the enabled text model to use as the prompt enhancer. Leave blank/null to use the engine's default.",
        examples=[None],
    )
    assistant_model: Optional[UUID] = Field(
        default=None,
        description="UID of the enabled text model to use as the assistant. Leave blank/null to use the engine's default.",
        examples=[None],
    )
