from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class NewFolderPayload(BaseModel):
    current_path: str = Field(
        ..., min_length=1, description="Existing folder path to create the new subfolder under.", examples=["images"]
    )
    name: str = Field(..., min_length=1, description="New folder name (no `/` or `\\`).", examples=["references"])


class DeleteFolderPayload(BaseModel):
    folder_path: str = Field(..., min_length=1, description="Folder path to delete.", examples=["images/references"])


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


class RenameFolderPayload(BaseModel):
    folder_path: str = Field(..., min_length=1, description="Folder path to rename.", examples=["images/drafts"])
    name: str = Field(..., min_length=1, description="New folder name (no `/` or `\\`).", examples=["approved"])


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
        ..., min_length=1, description="Folder paths to move.", examples=[["images/drafts"]]
    )
    destination: str = Field(..., min_length=1, description="Destination folder path.", examples=["images/approved"])


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
