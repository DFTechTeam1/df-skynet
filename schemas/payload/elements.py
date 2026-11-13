from typing import Optional
from pydantic import BaseModel, Field
from enums.elements import ElementTypes


class CreateElementPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: ElementTypes = Field(...)
    description: Optional[str] = Field(None, min_length=1, max_length=5000)
