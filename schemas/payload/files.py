import re
import unicodedata
from typing import Annotated, Any
from uuid import UUID
from pydantic import BaseModel, Field, field_validator

NAME_RE = re.compile(r"[A-Za-z0-9_ .\-#()@&]+")  # ASCII letters, digits, space and _ - . # ( ) @ &
MEDIA_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|mp4|mov|webm|avi|mkv)$", re.IGNORECASE)
NAME_MAX = 100  # Udin has no limit of its own; the filesystem caps a name at 255 bytes, a path at 4096
PATH_MAX = 1024
PathStr = Annotated[str, Field(min_length=1, max_length=PATH_MAX)]


def clean_name(value: str, kind: str, strip_ext: bool = False) -> str:
    """Normalize a user-typed name: NFC, trim spaces and dots (`report.` -> `report`, `.png` -> `png`). For files
    `strip_ext` also drops one trailing media extension, since the real one always comes from the stored row.
    `kind` is `file` or `folder` and picks the error key."""
    trim = " ."
    value = unicodedata.normalize("NFC", value).strip(trim)
    if strip_ext:
        value = MEDIA_EXT_RE.sub("", value).strip(trim)
    if not value:
        raise ValueError(f"{kind}_name_empty")
    if not NAME_RE.fullmatch(value):
        raise ValueError(f"invalid_{kind}_name")
    return value


class FolderPayload(BaseModel):
    path: str = Field(
        ...,
        min_length=1,
        max_length=PATH_MAX,
        description="POST: parent folder to create the new folder under. PATCH: folder to rename. Full path as shown in the file tree.",
        examples=["storage/DF-Engine/Wedding_7b804b30/upload/images"],
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=NAME_MAX,
        description="Folder name. Letters, numbers, spaces and _ - . # ( ) @ & only. Leading/trailing dots are removed.",
        examples=["Ms. Shinta (2026) & Co"],
    )

    @field_validator("path", mode="after")
    @classmethod
    def strip_path(cls, value: str) -> str:
        return value.strip("/")

    @field_validator("name", mode="after")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return clean_name(value, "folder")


class DeleteFilesPayload(BaseModel):
    file_uids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="File `uid`s to delete.",
        examples=[["b3f1c2d4-5678-4abc-9def-0123456789ab"]],
    )

    @field_validator("file_uids", mode="before")
    @classmethod
    def dedupe_file_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))


class RenameFilePayload(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=NAME_MAX,
        description="New file name. Letters, numbers, spaces and _ - . # ( ) @ & only. A typed media extension is ignored: the file's real extension is always kept.",
        examples=["standby v.1 (final) & edit"],
    )

    @field_validator("name", mode="after")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return clean_name(value, "file", strip_ext=True)


class MoveFilesPayload(BaseModel):
    file_uids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="File `uid`s to move.",
        examples=[["b3f1c2d4-5678-4abc-9def-0123456789ab"]],
    )
    destination: str = Field(
        ...,
        min_length=1,
        max_length=PATH_MAX,
        description="Full path of the destination folder.",
        examples=["storage/DF-Engine/Wedding_7b804b30/upload/images/approved"],
    )

    @field_validator("file_uids", mode="before")
    @classmethod
    def dedupe_file_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))

    @field_validator("destination", mode="after")
    @classmethod
    def strip_destination(cls, value: str) -> str:
        return value.strip("/")


class MoveFoldersPayload(BaseModel):
    folder_paths: list[PathStr] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Full paths of the folders to move. Must share the destination's storage (upload or generated) and type (images or videos).",
        examples=[["storage/DF-Engine/Wedding_7b804b30/upload/images/drafts"]],
    )
    destination: str = Field(
        ...,
        min_length=1,
        max_length=PATH_MAX,
        description="Full path of the destination folder.",
        examples=["storage/DF-Engine/Wedding_7b804b30/upload/images/approved"],
    )

    @field_validator("folder_paths", mode="after")
    @classmethod
    def dedupe_folder_paths(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(path.strip("/") for path in value))

    @field_validator("destination", mode="after")
    @classmethod
    def strip_destination(cls, value: str) -> str:
        return value.strip("/")


class SetArchivedPayload(BaseModel):
    file_uids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="File `uid`s to archive/unarchive.",
        examples=[["b3f1c2d4-5678-4abc-9def-0123456789ab"]],
    )
    is_archieved: bool = Field(True, description="True to archive, False to unarchive.", examples=[True])

    @field_validator("file_uids", mode="before")
    @classmethod
    def dedupe_file_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))


class SetFavoritedPayload(BaseModel):
    file_uids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="File `uid`s to favorite/unfavorite.",
        examples=[["b3f1c2d4-5678-4abc-9def-0123456789ab"]],
    )
    is_favorited: bool = Field(True, description="True to favorite, False to unfavorite.", examples=[True])

    @field_validator("file_uids", mode="before")
    @classmethod
    def dedupe_file_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))
