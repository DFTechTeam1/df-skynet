from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from uuid import UUID


class PromptTemplatePayload(BaseModel):
    """Payload to register a reusable prompt template.

    A prompt template holds the raw prompt text that gets injected as the base
    prompt whenever it is wired to a feature via `df_engine_feature_prompt_mappings`.
    `name` must be unique across all existing templates; `prompt` content may
    repeat (e.g. cloning a template under a new name to iterate on it).
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique, human-readable name identifying this prompt template.",
        examples=["system-learning"],
    )
    description: Optional[str] = Field(
        default=None,
        description="Free-text explanation of what this template is for and when it should be used.",
        examples=["Used to fine-tune the assistant's tone for onboarding conversations."],
    )
    is_active: bool = Field(
        default=True,
        description=(
            "Whether this template is available for use. Active templates can be selected "
            "when mapping a feature to a prompt; inactive templates are hidden from that "
            "selection but remain stored for history."
        ),
        examples=[True],
    )
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=16_000,
        description="The raw prompt text (markdown supported) that will be injected as the base prompt.",
        examples=[
            "You are a helpful onboarding assistant. Always respond in a warm, concise tone "
            "and guide the user through their first project setup step by step."
        ],
    )
    template_references: list[UUID] = Field(
        default_factory=list,
        description="UIDs of other prompt templates this template references. Duplicates are dropped.",
    )

    @field_validator("template_references")
    @classmethod
    def dedupe_references(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def references_must_be_in_prompt(self):
        if any(str(u) not in self.prompt for u in self.template_references):
            raise ValueError("prompt_template_reference_not_in_prompt")
        return self
