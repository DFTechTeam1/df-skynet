from pydantic import BaseModel, SerializerFunctionWrapHandler, field_validator, model_serializer, model_validator
from typing import Any, Optional, Literal, Union
from utils.formatter import format_udin_url, format_size, format_datetime, format_usd, format_idr, format_user_employees
from schemas.format.action import UploadedFileAction, GeneratedFileAction, FolderAction

ICON_COLOR_MAP = {
    "image": {"icon": "mdi-image", "color": "blue"},
    "image_edit": {"icon": "mdi-image-edit", "color": "indigo"},
    "video": {"icon": "mdi-video", "color": "purple"},
    "element": {"icon": "mdi-shape", "color": "teal"},
    "storyboard": {"icon": "mdi-view-sequential", "color": "orange"},
    "keyframe": {"icon": "mdi-camera-image", "color": "cyan"},
    "motion": {"icon": "mdi-motion", "color": "deep-purple"},
    "chat": {"icon": "mdi-chat-outline", "color": "green"},
    "enhancer": {"icon": "mdi-auto-fix", "color": "amber"},
    "folder": {"icon": "mdi-folder", "color": "amber"},
}


class IconKind(BaseModel):
    kind: Literal[
        "image", "image_edit", "video", "element", "storyboard", "keyframe", "motion", "chat", "enhancer", "folder"
    ]
    icon: Optional[str] = None
    color: Optional[str] = None

    @model_validator(mode="after")
    def set_icon_color(self):
        meta = ICON_COLOR_MAP[self.kind]
        self.icon = self.icon or meta["icon"]
        self.color = self.color or meta["color"]
        return self


class FilesPathUrl(BaseModel):
    """Uploaded files and folders: keep the storage `path` and add the udin `url` next to it."""

    path: Optional[str] = None
    url: Optional[str] = None

    @model_validator(mode="after")
    def set_url(self):
        if self.path:
            self.url = format_udin_url(self.path)
        return self


class GeneratedUrl(BaseModel):
    """Generated files: a single `path`, null by default, replaced by its udin url when there is one."""

    path: Optional[str] = None

    @field_validator("path")
    @classmethod
    def set_path_url(cls, v):
        return format_udin_url(v) if v else None


class HumanizeTimezone(BaseModel):
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    favourited_at: Optional[str] = None
    archieved_at: Optional[str] = None

    @field_validator("created_at", "updated_at", "favourited_at", "archieved_at", mode="before")
    @classmethod
    def set_time(cls, v):
        try:
            return format_datetime(v)
        except ValueError:
            return v


class HumanizeFilesize(BaseModel):
    size: Optional[str] = None

    @field_validator("size", mode="before")
    @classmethod
    def set_filesize(cls, v):
        if isinstance(v, str) and v.isdigit():
            v = int(v)
        return format_size(v) if isinstance(v, (int, float)) else v


class GenerationReference(IconKind, GeneratedUrl, HumanizeFilesize, HumanizeTimezone):
    """A file a generation was based on: another generated result, or an uploaded file."""

    type: Literal["generated", "uploaded"] = "generated"
    file_uid: Optional[str] = None
    name: Optional[str] = None
    version: Optional[int] = None
    task: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None
    full_prompt: Optional[str] = None
    parameter: Optional[dict[str, Any]] = None
    creator: Optional[dict[str, Any]] = None
    updater: Optional[dict[str, Any]] = None


class GenerationVariant(IconKind, GeneratedUrl, HumanizeFilesize, HumanizeTimezone):
    """One version of a generated file. Nothing to act on from here, and no versions or references of its own."""

    file_uid: Optional[str] = None
    generation_uid: Optional[str] = None
    parent_id: Optional[int] = None
    name: Optional[str] = None
    type: str = "generated"
    is_main: Optional[bool] = None
    version: Optional[int] = None
    status: Optional[str] = None
    task_uid: Optional[str] = None
    song_uid: Optional[str] = None
    task: Optional[str] = None
    cost_usd: Optional[str] = None
    cost_idr: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None
    full_prompt: Optional[str] = None
    parameter: Optional[dict[str, Any]] = None
    creator: Optional[dict[str, Any]] = None
    updater: Optional[dict[str, Any]] = None


class UserGeneratedFile(GenerationVariant):
    """The main file of a generation: a variant that can also be acted on and carries its versions and references."""

    action: Optional[GeneratedFileAction] = None
    variants: list[GenerationVariant] = []
    references: list[GenerationReference] = []


class UserUploadedFile(IconKind, FilesPathUrl, HumanizeFilesize, HumanizeTimezone):
    file_uid: str
    type: str = "uploaded"
    name: str
    task_uid: Optional[str] = None
    song_uid: Optional[str] = None
    task: Optional[str] = None
    creator: Optional[dict[str, Any]] = None
    updater: Optional[dict[str, Any]] = None
    action: Optional[Union[UploadedFileAction, FolderAction]] = None

    @model_serializer(mode="wrap")
    def serialize_folder(self, handler: SerializerFunctionWrapHandler):
        data = handler(self)
        if self.kind != "folder":
            return data
        return {k: data[k] for k in ("name", "path", "kind", "icon", "color", "action", "creator", "updater")}


class TreeFileRefactored(BaseModel):
    file_uid: Optional[str] = None
    name: str
    path: str
    url: str
    type: Literal["generated", "upload"] = "generated"
    kind: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    task_uid: Optional[str] = None
    song_uid: Optional[str] = None
    task: Optional[str] = None
    creator: Optional[dict[str, Any]] = None
    updater: Optional[dict[str, Any]] = None
    action: Union[GeneratedFileAction, UploadedFileAction]


class TreeFolderRefactored(BaseModel):
    name: str
    path: str
    kind: Literal["folder"] = "folder"
    icon: str = ICON_COLOR_MAP["folder"]["icon"]
    color: str = ICON_COLOR_MAP["folder"]["color"]
    action: FolderAction
    creator: Optional[dict[str, Any]] = None
    updater: Optional[dict[str, Any]] = None
    files: list[TreeFileRefactored] = []
    children: list["TreeFolderRefactored"] = []
