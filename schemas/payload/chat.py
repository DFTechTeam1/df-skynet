from pydantic import BaseModel, ConfigDict, Field

PLACEHOLDER_MAX_CHARS = 100


class RenameChatPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    placeholder: str = Field(min_length=1, max_length=PLACEHOLDER_MAX_CHARS, description="New chat name.")
