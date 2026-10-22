from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field
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


class PromptEnhancerResult(BaseModel):
    prompt: str
    enhance_uid: UUID
