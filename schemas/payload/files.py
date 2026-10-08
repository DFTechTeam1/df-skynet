from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class FolderPayload(BaseModel):
    path: str = Field(
        ...,
        min_length=1,
        description="POST: parent folder to create the new folder under. PATCH: folder to rename. Full path as shown in the file tree.",
        examples=["storage/DF-Engine/Wedding_7b804b30/upload/images"],
    )
    name: str = Field(..., min_length=1, description="Folder name (no `/` or `\\`).", examples=["references"])

    @field_validator("path", mode="after")
    @classmethod
    def strip_path(cls, value: str) -> str:
        return value.strip("/")

    @field_validator("name", mode="after")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value or value in (".", "..") or "/" in value or "\\" in value:
            raise ValueError("invalid_folder_name")
        return value


class DeleteFilesPayload(BaseModel):
    file_uids: list[UUID] = Field(
        ...,
        min_length=1,
        description="File `uid`s to delete.",
        examples=[["b3f1c2d4-5678-4abc-9def-0123456789ab"]],
    )


class RenameFilePayload(BaseModel):
    file_uid: UUID = Field(..., description="File `uid` to rename.", examples=["b3f1c2d4-5678-4abc-9def-0123456789ab"])
    name: str = Field(
        ..., min_length=1, description="New name (extension is always preserved).", examples=["final_render"]
    )


class MoveFilesPayload(BaseModel):
    file_uids: list[UUID] = Field(
        ...,
        min_length=1,
        description="File `uid`s to move.",
        examples=[["b3f1c2d4-5678-4abc-9def-0123456789ab"]],
    )
    destination: str = Field(..., min_length=1, description="Destination folder path.", examples=["images/approved"])


class MoveFoldersPayload(BaseModel):
    folder_paths: list[str] = Field(
        ...,
        min_length=1,
        description="Full paths of the folders to move. Must share the destination's storage (upload or generated) and type (images or videos).",
        examples=[["storage/DF-Engine/Wedding_7b804b30/upload/images/drafts"]],
    )
    destination: str = Field(
        ...,
        min_length=1,
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
        description="File `uid`s to favorite/unfavorite.",
        examples=[["b3f1c2d4-5678-4abc-9def-0123456789ab"]],
    )
    is_favorited: bool = Field(True, description="True to favorite, False to unfavorite.", examples=[True])

    @field_validator("file_uids", mode="before")
    @classmethod
    def dedupe_file_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))
