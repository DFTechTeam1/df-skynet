from uuid import UUID
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ChatAssistant(BaseModel):
    """How much of the earlier conversation the assistant is given as context."""

    max_previous_conversation: int = Field(
        default=0,
        ge=0,
        description=(
            "How many of the most recent messages from the same chat to include as "
            "context when the assistant answers. 0 means each message is answered on "
            "its own, with no memory of what was said earlier in the chat."
        ),
    )


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


class ProjectLimitOverride(BaseModel):
    """A per-project override of the generation cap."""

    project_uid: UUID = Field(
        ...,
        description="UID of the project this override applies to.",
        examples=["c6f66cb0-9c62-46f4-9228-1604e26c09d9"],
    )
    limit: int = Field(
        default=0,
        ge=0,
        description="Generation cap for this project. 0 means unlimited.",
        examples=[0],
    )


class ProjectClassLimit(BaseModel):
    """A generation cap for one project class. Classes not listed default to 0."""

    project_class_id: int = Field(..., description="ID of the project class this limit applies to.", examples=[1])
    limit: int = Field(
        default=0,
        ge=0,
        description="Generation cap for this project class. 0 means no class-specific limit.",
        examples=[0],
    )


class AdminSettingPayload(BaseModel):
    """Full DF Engine admin settings — every field except `project_limit_override`
    must be supplied on save (not a partial diff), though each has a sensible
    default so the settings page can always submit a complete, valid payload."""

    admin_view: AdminView = Field(default_factory=AdminView)
    limit: UserRateLimit = Field(default_factory=UserRateLimit)
    project_limit_override: Optional[ProjectLimitOverride] = Field(
        default=None,
        description=(
            "Set one project's generation cap. Omit (or null) to leave every existing per-project override untouched."
        ),
    )
    project_class_limits: list[ProjectClassLimit] = Field(
        default_factory=list,
        min_length=1,
        description="Per-class generation caps. When provided, at least one entry; duplicate project_class_id keeps the last.",
        examples=[[{"project_class_id": 1, "limit": 0}]],
    )
    storyboard: UserStoryboard = Field(default_factory=UserStoryboard)
    compose_input: UserComposeInput = Field(default_factory=UserComposeInput)
    chat_assistant: ChatAssistant = Field(default_factory=ChatAssistant)
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

    @field_validator("project_class_limits")
    @classmethod
    def _dedupe_project_class_limits(cls, value: list[ProjectClassLimit]) -> list[ProjectClassLimit]:
        """Collapse repeated project_class_id, keeping the last value given."""
        deduped: dict[int, ProjectClassLimit] = {}
        for item in value:
            deduped[item.project_class_id] = item
        return list(deduped.values())
