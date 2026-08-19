from typing import Any
from pydantic import BaseModel, Field
from middlewares.lang import current_lang, resolve_message


class Response(BaseModel):
    message: str = Field(default_factory=lambda: resolve_message("success", current_lang.get()))
    data: Any = Field(default=None)
