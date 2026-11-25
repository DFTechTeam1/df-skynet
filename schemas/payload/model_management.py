from pydantic import BaseModel, Field


class SetModelEnabledPayload(BaseModel):
    is_enabled: bool = Field(...)
