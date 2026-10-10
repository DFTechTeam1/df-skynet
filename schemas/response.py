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
        description="How well the message is an idea or rough prompt to expand into a detailed generation prompt (1 = fully matches).",
    )
    prompt_injection: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How strongly the message tries to manipulate the system, jailbreak it or ignore instructions (1 = certain).",
    )
    nfsw: float = Field(
        default=0, ge=0, le=1, description="How sexual, explicit or graphic the message is (1 = certain)."
    )
    image_generation: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How well the message describes an image to generate or edit (1 = fully matches).",
    )
    video_generation: float = Field(
        default=0, ge=0, le=1, description="How well the message describes a video to generate (1 = fully matches)."
    )
    storyboard_generation: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How well the message describes a multi-scene storyboard (1 = fully matches).",
    )
    chat_assistant: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How well the message is a question or chat with an assistant (1 = fully matches).",
    )
    element_generation: float = Field(
        default=0,
        ge=0,
        le=1,
        description="How well the message describes a single reusable element or asset (1 = fully matches).",
    )


class PromptEnhancerResult(BaseModel):
    prompt: str
    enhance_uid: UUID
