from uuid import UUID
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class AdminView(BaseModel):
    """Library visibility rules."""

    see_all_asset: bool = Field(
        default=True,
        description=(
            "When on, every user can see other users' generated assets in the Library. "
            "When off, a user sees only their own assets plus anything shared with them "
            "(Global / Role)."
        ),
    )


class ProjectClassLimitations(BaseModel):
    """Usage limits for one project class (e.g. class A, A+, B). Every project in
    that class inherits these limits."""

    id: int = Field(default=1, description="ID of the project class these limits apply to.", ge=1)
    token_usage_limit: int = Field(
        default=1,
        description="Spend cap on AI generations per project, in USD. Once reached, that project can't generate until the cap is raised.",
        ge=1,
    )
    concurent_generations: int = Field(
        default=1,
        description="How many generations a single user can run at the same time in this project class.",
        ge=1,
    )
    compose_input_max_chars: int = Field(
        default=2000,
        description="Longest prompt (in characters) a user can send when generating an image or video.",
        ge=1,
    )
    storyboard_prompt_chars: int = Field(
        default=2000,
        description="Longest prompt (in characters) a user can send when generating a storyboard.",
        ge=1,
    )
    max_scene_per_storyboard: int = Field(
        default=2000,
        description="Most scenes a single storyboard can hold.",
        ge=1,
    )
    max_shot_per_scene: int = Field(
        default=2000,
        description="Most shots a single scene can hold.",
        ge=1,
    )


class ProjectSettingPayload(BaseModel):
    """Per-project override of the generation limits. When no override is saved a
    project inherits the limits configured for its class in the global settings."""

    token_usage_limit: int = Field(
        default=1,
        description="Spend cap on AI generations for this project, in USD.",
        ge=1,
    )
    concurent_generations: int = Field(
        default=1,
        description="How many generations a single user can run at the same time in this project.",
        ge=1,
    )
    compose_input_max_chars: int = Field(
        default=2000,
        description="Longest prompt (in characters) a user can send when generating an image or video.",
        ge=1,
    )
    storyboard_prompt_chars: int = Field(
        default=2000,
        description="Longest prompt (in characters) a user can send when generating a storyboard.",
        ge=1,
    )
    max_scene_per_storyboard: int = Field(
        default=2000,
        description="Most scenes a single storyboard can hold.",
        ge=1,
    )
    max_shot_per_scene: int = Field(
        default=2000,
        description="Most shots a single scene can hold.",
        ge=1,
    )


class AdminGlobalSettingPayload(BaseModel):
    """Workspace-wide DF Engine settings. This is a full replace — send the whole
    document, not just the fields you changed. Every field has a default so the
    settings page can always submit a complete payload."""

    admin_view: AdminView = Field(
        default_factory=AdminView,
        description="Library visibility rules for admins.",
    )
    project_class_limitations: list[ProjectClassLimitations] = Field(
        default_factory=list,
        description=(
            "Usage limits per project class. Include one entry per class you want to "
            "set; if the same class ID appears twice, the last one wins. Classes you "
            "leave out keep their current limits."
        ),
    )

    enhancer_model: Optional[UUID] = Field(
        default=None,
        description=(
            "ID of the text model that rewrites/improves user prompts before generation. "
            "Must be a model that is currently enabled. Leave empty to use the engine default."
        ),
        examples=[None],
    )
    assistant_model: Optional[UUID] = Field(
        default=None,
        description=(
            "ID of the text model that powers the in-app assistant/chat. "
            "Must be a model that is currently enabled. Leave empty to use the engine default."
        ),
        examples=[None],
    )

    @field_validator("project_class_limitations")
    @classmethod
    def dedupe_project_class_limitations(cls, value: list[ProjectClassLimitations]) -> list[ProjectClassLimitations]:
        """Collapse repeated project class IDs, keeping the last value given."""
        deduped: dict[int, ProjectClassLimitations] = {}
        for item in value:
            deduped[item.id] = item
        return list(deduped.values())
