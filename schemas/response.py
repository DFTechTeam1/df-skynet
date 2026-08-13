from typing import Any

from pydantic import BaseModel, Field


class Response(BaseModel):
    message: str = Field(default="Success")
    data: Any = Field(default=None)
