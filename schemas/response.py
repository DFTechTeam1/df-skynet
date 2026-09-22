from typing import Any, Optional
from pydantic import BaseModel, Field
from middlewares.lang import current_lang, resolve_message


class Response(BaseModel):
    message: str = Field(default_factory=lambda: resolve_message("success", current_lang.get()))
    data: Any = Field(default=None)


class PaginationResponse(BaseModel):
    paginated: Optional[list[dict[str, Any]]] = None
    totalData: Optional[int] = None


class OpenrouterRankingResponse(BaseModel):
    prompt_injection: float = Field(ge=0, le=1, description="Measure prompt injection.", default=0)
    image_generation: float = Field(
        ge=0, le=1, description="Measure prompt is related to image generation task.", default=0
    )
    video_generation: float = Field(
        ge=0, le=1, description="Measure prompt is related to video generation task.", default=0
    )
    chat_assistant: float = Field(
        ge=0, le=1, description="Measure prompt is related to chat assistant task.", default=0
    )
