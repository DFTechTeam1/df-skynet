from typing import Any, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from middlewares.lang import current_lang, resolve_message


class Response(BaseModel):
    message: str = Field(default_factory=lambda: resolve_message("success", current_lang.get()))
    data: Any = Field(default=None)


class PaginationResponse(BaseModel):
    paginated: Optional[list[dict[str, Any]]] = None
    totalData: Optional[int] = None


class PromptValidationResponse(BaseModel):
    prompt_enhancement: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How much the message is NOT an idea or rough prompt that can be expanded into a detailed generation prompt (1 = certainly not).",
    )
    prompt_injection: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How strongly the message tries to manipulate the system, jailbreak it or ignore instructions (1 = certain).",
    )
    nfsw: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How sexual, explicit or violent the message is, or how much it names a real brand (1 = certain).",
    )
    image_generation: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How much the message does NOT describe a still image to generate or edit (1 = certainly not).",
    )
    video_generation: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How much the message does NOT describe a video to generate (1 = certainly not).",
    )
    storyboard_generation: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How much the message does NOT describe a multi-scene storyboard (1 = certainly not).",
    )
    chat_assistant: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How much the message is NOT a question or chat with an assistant (1 = certainly not).",
    )
    element_generation: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How much the message does NOT describe a single reusable element or asset (1 = certainly not).",
    )


class EnhancerReference(BaseModel):
    uid: UUID
    source: Literal["upload", "generated"]
    name: str


class PromptEnhancerResult(BaseModel):
    prompt: str
    enhance_uid: UUID
    references: list[EnhancerReference] = Field(default_factory=list)


class PromptGuardrailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_injection: bool = Field(default=False)
    nfsw: bool = Field(default=False)
    prompt_enhancement: bool = Field(default=True)
    image_generation: bool = Field(default=True)
    video_generation: bool = Field(default=True)
    storyboard_generation: bool = Field(default=True)
    chat_assistant: bool = Field(default=True)
    element_generation: bool = Field(default=True)

    @model_validator(mode="after")
    def all_flags_present(self) -> "PromptGuardrailResponse":
        """The defaults only keep the request schema simple; a reply must state every flag itself,
        otherwise a missing `prompt_injection` would silently count as false."""
        missing = set(type(self).model_fields) - self.model_fields_set
        if missing:
            raise ValueError(f"guardrail reply is missing flags: {sorted(missing)}")
        return self
