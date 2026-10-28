from uuid import UUID
from typing import Optional, Literal
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
        default=10,
        description=(
            "Spend cap on AI generations per project in this class, in whole USD "
            "(e.g. 50, 100). Once reached, projects in this class can't generate until "
            "the cap is raised."
        ),
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
    token_limit_threshold: float = Field(
        default=0.8,
        ge=0,
        le=1,
        description=(
            "Fraction of a project's token allowance (0-1) at which projects in this "
            "class warn the user they're close to the cap. Default 0.8 = warn at 80%."
        ),
        examples=[0.8],
    )


class ProjectSettingPayload(BaseModel):
    """Per-project override of the generation limits. When no override is saved a
    project inherits the limits configured for its class in the global settings."""

    token_usage_limit: int = Field(
        default=10,
        description="Spend cap on AI generations for this project, in whole USD.",
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
    token_limit_threshold: float = Field(
        default=0.8,
        ge=0,
        le=1,
        description=(
            "Per-project token-limit warning threshold (0-1). Defaults to 0.8. A project "
            "with a saved override always carries its own value; projects with no saved "
            "row fall back to their project class's value from the global settings."
        ),
        examples=[0.8],
    )


PromptValidationType = Literal[
    "prompt_enhancement",
    "prompt_injection",
    "nfsw",
    "image_generation",
    "video_generation",
    "storyboard_generation",
    "chat_assistant",
    "element_generation",
]


class PromptValidation(BaseModel):
    type: PromptValidationType = Field(description="Type of prompt validation to perform.")
    threshold: float = Field(
        default=0,
        ge=0,
        le=1,
        description="Threshold for the prompt validation. If not provided 0 then no validation will be performed. If provided > 0, the prompt will be validated against this threshold.",
    )
    instruction: str = Field(
        description="What the checker scores for this type. Required; only used when the threshold is above 0.",
        min_length=1,
        max_length=16_000,
    )


class AdminGlobalSettingPayload(BaseModel):
    """Workspace-wide DF Engine settings. This is a full replace — send the whole
    document, not just the fields you changed. Every field has a default so the
    settings page can always submit a complete payload."""

    admin_view: AdminView = Field(
        default_factory=AdminView,
        description="Library visibility rules for admins.",
    )
    folder_depth_limit: int = Field(
        default=4,
        description=(
            "Deepest a subfolder chain may nest under a type root (e.g. upload/images) "
            "before create/move folder requests are rejected."
        ),
        ge=1,
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
    prompt_guardrails: Optional[list[PromptValidation]] = Field(
        default=None,
        min_length=1,
        max_length=len(PromptValidationType.__args__),
        description=(
            "Prompt guardrails checked before generating or enhancing. Each rule has a type, a "
            "threshold (0 = off, above 0 = on) and the instruction the checker scores against. "
            "Omit the field to keep the saved rules; send null to clear them (no guardrails run)."
        ),
    )

    @field_validator("prompt_guardrails")
    @classmethod
    def dedupe_prompt_guardrails(cls, value: Optional[list[PromptValidation]]) -> Optional[list[PromptValidation]]:
        """Collapse repeated validation types, keeping the last value given."""
        if value is None:
            return None
        return list({item.type: item for item in value}.values())

    @field_validator("project_class_limitations")
    @classmethod
    def dedupe_project_class_limitations(cls, value: list[ProjectClassLimitations]) -> list[ProjectClassLimitations]:
        """Collapse repeated project class IDs, keeping the last value given."""
        deduped: dict[int, ProjectClassLimitations] = {}
        for item in value:
            deduped[item.id] = item
        return list(deduped.values())
