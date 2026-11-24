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


class EnhancerReference(BaseModel):
    uid: UUID
    source: Literal["upload", "generated"]
    name: str


class PromptEnhancerResult(BaseModel):
    prompt: str
    enhance_uid: UUID
    references: list[EnhancerReference] = Field(default_factory=list)
