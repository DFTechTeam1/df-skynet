from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator
from schemas.format.base import TimezoneMeta, CreatorUpdaterMeta, GenerationFileAction, UploadedFileAction
from schemas.format.files import ICON_COLOR_MAP
from utils.formatter import format_size, format_udin_url


class GeneratedFile(TimezoneMeta, CreatorUpdaterMeta):
    size: Optional[str] = Field(default=None)
    path: Optional[str] = Field(default=None)
    kind: Literal["image", "image_edit"] = Field(...)
    icon: str = Field(...)
    color: str = Field(...)
    id: Optional[int] = Field(default=None)
    file_uid: Optional[str] = Field(default=None)
    generation_uid: str = Field(...)
    name: Optional[str] = Field(default=None)
    type: Literal["generated"] = Field(...)
    task_uid: Optional[str] = Field(default=None)
    song_uid: Optional[str] = Field(default=None)
    task: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    action: GenerationFileAction = Field(...)

    @classmethod
    def from_result(cls, result: dict[str, Any], viewer_id: int, can_override: bool) -> "GeneratedFile":
        generation = result["generation"]
        task = generation.get("task") or {}
        song = generation.get("song") or {}
        favourites = result.get("favourites") or []
        return cls.format(
            {
                **result,
                **ICON_COLOR_MAP[generation["kind"]],
                "favourited_at": favourites[0]["favourited_at"] if favourites else None,
                "size": format_size(result["size"]),
                "path": format_udin_url(result["path"]),
                "kind": generation["kind"],
                "file_uid": result["uid"],
                "generation_uid": generation["uid"],
                "type": "generated",
                "task_uid": task.get("uid"),
                "song_uid": song.get("uid"),
                "task": task.get("name") or song.get("name"),
                "model": (generation.get("model_option") or {}).get("name"),
                "action": GenerationFileAction.format(result, viewer_id, can_override),
            }
        )


class UploadedFile(TimezoneMeta, CreatorUpdaterMeta):
    size: Optional[str] = Field(default=None)
    path: str = Field(...)
    url: str = Field(...)
    kind: str = Field(...)
    icon: str = Field(...)
    color: str = Field(...)
    id: int = Field(...)
    file_uid: str = Field(...)
    type: Literal["uploaded"] = Field(...)
    name: str = Field(...)
    task_uid: Optional[str] = Field(default=None)
    song_uid: Optional[str] = Field(default=None)
    task: Optional[str] = Field(default=None)
    action: UploadedFileAction = Field(...)
    archieved_at: Optional[str] = Field(default=None, exclude=True)

    @classmethod
    def from_result(cls, result: dict[str, Any], viewer_id: int, can_override: bool) -> "UploadedFile":
        """Builds the file from a serialized `DfEngineUploadFiles` with its relationships loaded."""
        task = result.get("task") or {}
        song = result.get("song") or {}
        return cls.format(
            {
                **result,
                **ICON_COLOR_MAP[result["type"]],
                "kind": result["type"],
                "type": "uploaded",
                "size": format_size(result["size"]),
                "url": format_udin_url(result["path"]),  # `path` stays the storage path
                "file_uid": result["uid"],
                "task_uid": task.get("uid"),
                "song_uid": song.get("uid"),
                "task": task.get("name") or song.get("name"),
                "action": UploadedFileAction.format(result["created_by"] == viewer_id, can_override),
            }
        )


class ReferencePicker(BaseModel):
    type: Literal["Image Generations", "Elements", "Image Uploads"] = Field(...)
    total: int = Field(default=0)
    files: Union[list[GeneratedFile], list[UploadedFile]] = Field(...)

    @model_validator(mode="after")
    def count_files(self) -> "ReferencePicker":
        self.total = len(self.files)
        return self
