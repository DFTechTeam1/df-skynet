import re
import unicodedata
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from enums.elements import ElementTypes


class CreateElementPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: ElementTypes = Field(...)
    description: Optional[str] = Field(None, min_length=1, max_length=5000)


class RenameElementFilePayload(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="New file name. Letters, numbers, spaces and _ - . # ( ) @ & only. A typed media extension is ignored: the file's real extension is always kept.",
        examples=["standby v.1 (final) & edit"],
    )

    @field_validator("name", mode="after")
    @classmethod
    def valid_name(cls, value: str) -> str:
        NAME_RE = re.compile(r"[A-Za-z0-9_ .\-#()@&]+")
        MEDIA_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|mp4|mov|webm|avi|mkv)$", re.IGNORECASE)

        value = unicodedata.normalize("NFC", value).strip(" .")
        value = MEDIA_EXT_RE.sub("", value).strip(" .")
        if not value:
            raise ValueError("file_name_empty")
        if not NAME_RE.fullmatch(value):
            raise ValueError("invalid_file_name")
        return value
