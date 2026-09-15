from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class NewFolderPayload(BaseModel):
    current_path: str = Field(..., min_length=1, description="Existing folder path to create the new subfolder under.")
    name: str = Field(..., min_length=1, description="New folder name (no `/` or `\\`).")


class DeleteFolderPayload(BaseModel):
    folder_path: str = Field(..., min_length=1, description="Folder path to delete.")


class DeleteFilesPayload(BaseModel):
    file_uids: list[UUID] = Field(..., min_length=1, description="File `uid`s to delete.")


class RenameFilePayload(BaseModel):
    file_uid: UUID = Field(..., description="File `uid` to rename.")
    name: str = Field(..., min_length=1, description="New name (extension is always preserved).")


class RenameFolderPayload(BaseModel):
    folder_path: str = Field(..., min_length=1, description="Folder path to rename.")
    name: str = Field(..., min_length=1, description="New folder name (no `/` or `\\`).")


class MoveFilesPayload(BaseModel):
    file_uids: list[UUID] = Field(..., min_length=1, description="File `uid`s to move.")
    destination: str = Field(..., min_length=1, description="Destination folder path.")


class MoveFoldersPayload(BaseModel):
    folder_paths: list[str] = Field(..., min_length=1, description="Folder paths to move.")
    destination: str = Field(..., min_length=1, description="Destination folder path.")


class SetArchivedPayload(BaseModel):
    file_uids: list[UUID] = Field(..., min_length=1, description="File `uid`s to archive/unarchive.")
    is_archieved: bool = Field(True, description="True to archive, False to unarchive.")

    @field_validator("file_uids", mode="before")
    @classmethod
    def dedupe_file_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))


class SetFavoritedPayload(BaseModel):
    file_uids: list[UUID] = Field(..., min_length=1, description="File `uid`s to favorite/unfavorite.")
    is_favorited: bool = Field(True, description="True to favorite, False to unfavorite.")

    @field_validator("file_uids", mode="before")
    @classmethod
    def dedupe_file_uids(cls, value: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(UUID(str(uid))) for uid in value))
