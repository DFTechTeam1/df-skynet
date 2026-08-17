from pydantic import BaseModel, Field
from typing import Optional


class CreatePromptTemplatePayload(BaseModel):
    """Payload to register a reusable prompt template.

    A prompt template holds the raw prompt text that gets injected as the base
    prompt whenever it is wired to a page action via `df_engine_action_mappings`.
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
        min_length=1,
        description="Free-text explanation of what this template is for and when it should be used.",
        examples=[
            "Used to fine-tune the assistant's tone for onboarding conversations."
        ],
    )
    is_active: bool = Field(
        default=True,
        description=(
            "Whether this template is available for use. Active templates can be selected "
            "when mapping a page action to a prompt; inactive templates are hidden from that "
            "selection but remain stored for history."
        ),
        examples=[True],
    )
    prompt: str = Field(
        ...,
        min_length=1,
        # `df_engine_prompt_templates.prompt` is a MySQL TEXT column (64KB byte cap).
        # Bounded well under that, accounting for multi-byte (utf8mb4) characters.
        max_length=16_000,
        description="The raw prompt text (markdown supported) that will be injected as the base prompt.",
        examples=[
            "You are a helpful onboarding assistant. Always respond in a warm, concise tone "
            "and guide the user through their first project setup step by step."
        ],
    )
