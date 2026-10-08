from typing import Any, Literal, Optional, Union
from pydantic import BaseModel
from services.mysql.model.df_engine_generations import GENERATION_KIND_ICON_COLOR
from services.mysql.model.df_engine_upload_files import UPLOAD_TYPE_ICON_COLOR, UploadFileTypes
from config.variables import USD_TO_IDR_RATE
from utils.formatter import format_size, format_datetime, format_udin_url, format_user_employees, format_idr, format_usd


def _is_image(path: str) -> bool:
    return "/videos/" not in path


class GenerationAction(BaseModel):
    can_archieve: bool
    can_unarchieve: bool
    can_set_main: bool
    can_favorited: bool
    can_unfavorited: bool
    can_download: bool
    can_fetch_detail: bool
    can_use_as_reference: bool
    can_use_as_edit: bool
    can_rename: bool = False
    can_choose_to_move: bool = False

    @classmethod
    def from_result(cls, result: dict[str, Any], is_owner: bool) -> "GenerationAction":
        return cls(
            can_archieve=is_owner and result["archieved_at"] is None and result["is_main"] is False,
            can_unarchieve=is_owner and result["archieved_at"] is not None,
            can_set_main=is_owner and result["is_main"] is False,
            can_favorited=is_owner and result["favourited_at"] is None,
            can_unfavorited=is_owner and result["favourited_at"] is not None,
            can_download=True,
            can_fetch_detail=True,
            can_use_as_reference=_is_image(result["path"]),
            can_use_as_edit=_is_image(result["path"]) and is_owner,
            can_rename=is_owner,
            can_choose_to_move=is_owner and result["archieved_at"] is None,
        )


class ReferenceAction(BaseModel):
    can_fetch_detail: bool = True
    can_use_as_reference: bool

    @classmethod
    def from_result(cls, path: str) -> "ReferenceAction":
        return cls(can_use_as_reference=_is_image(path))


class GenerationResultRecord(BaseModel):
    id: Optional[int] = None
    flag_created_at: Optional[str] = None
    flag_favourited_at: Optional[str] = None
    flag_archieved_at: Optional[str] = None
    kind: Optional[str] = None
    file_uid: Optional[Any] = None
    generation_uid: Optional[str] = None
    parent_id: Optional[int] = None
    name: Optional[str] = None
    is_main: Optional[bool] = None
    path: Optional[str] = None
    size: Optional[str] = None
    version: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    favourited_at: Optional[str] = None
    archieved_at: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = None
    creator: Optional[dict[str, Any]] = None
    cost_usd: Optional[str] = None
    cost_idr: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None
    full_prompt: Optional[str] = None
    parameter: Optional[dict[str, Any]] = None
    action: Optional[GenerationAction] = None

    @classmethod
    def from_result(cls, result: dict[str, Any], user_id: Optional[int] = None) -> "GenerationResultRecord":
        generation = result.get("generation") or {}
        kind = generation.get("kind")
        model_option = generation.get("model_option")
        is_owner = user_id is not None and result["created_by"] == user_id
        return cls(
            id=result.get("id"),
            flag_created_at=result["created_at"],
            flag_favourited_at=result["favourited_at"],
            flag_archieved_at=result["archieved_at"],
            kind=kind,
            file_uid=result["uid"],
            generation_uid=generation.get("uid"),
            parent_id=result["parent_id"],
            name=result["name"],
            is_main=result["is_main"],
            path=format_udin_url(result["path"]),
            size=format_size(result["size"]),
            version=result["version"],
            created_at=format_datetime(result["created_at"]),
            updated_at=format_datetime(result.get("updated_at")),
            favourited_at=format_datetime(result["favourited_at"]),
            archieved_at=format_datetime(result["archieved_at"]),
            icon=GENERATION_KIND_ICON_COLOR.get(kind, {}).get("icon"),  # type: ignore
            color=GENERATION_KIND_ICON_COLOR.get(kind, {}).get("color"),  # type: ignore
            status=generation.get("status"),
            creator=format_user_employees(result.get("created_by_user")),
            cost_usd=format_usd(generation.get("cost")),
            cost_idr=format_idr(generation.get("cost"), USD_TO_IDR_RATE),
            model=(model_option or {}).get("name"),
            prompt=generation.get("prompt"),
            full_prompt=generation.get("full_prompt"),
            parameter=generation.get("parameter"),
            action=GenerationAction.from_result(result, is_owner),
        )

    @classmethod
    def pending(cls, generation: dict[str, Any]) -> "GenerationResultRecord":
        """A queued/processing generation with no result yet — same shape as `from_result`,
        but every file-specific field is empty and every action is False since there's
        nothing yet to download, archive, favorite, or set as main."""
        kind = generation.get("kind")
        model_option = generation.get("model_option")
        return cls(
            flag_created_at=generation.get("created_at"),
            kind=kind,
            generation_uid=generation.get("uid"),
            is_main=False,
            created_at=format_datetime(generation.get("created_at")),
            icon=GENERATION_KIND_ICON_COLOR.get(kind, {}).get("icon"),  # type: ignore
            color=GENERATION_KIND_ICON_COLOR.get(kind, {}).get("color"),  # type: ignore
            status=generation.get("status"),
            creator=format_user_employees(generation.get("created_by_user")),
            cost_usd=format_usd(generation.get("cost")),
            cost_idr=format_idr(generation.get("cost"), USD_TO_IDR_RATE),
            model=(model_option or {}).get("name"),
            prompt=generation.get("prompt"),
            full_prompt=generation.get("full_prompt"),
            parameter=generation.get("parameter"),
            action=GenerationAction(
                can_archieve=False,
                can_unarchieve=False,
                can_set_main=False,
                can_favorited=False,
                can_unfavorited=False,
                can_download=False,
                can_fetch_detail=False,
                can_use_as_reference=False,
                can_use_as_edit=False,
                can_rename=False,
                can_choose_to_move=False,
            ),
        )


class GenerationReferenceRecord(BaseModel):
    type: str = "generated"
    uid: Any
    created_at: Optional[str]
    name: str
    path: str
    size: str
    version: int
    kind: Optional[str]
    prompt: Optional[str]
    full_prompt: Optional[str]
    model: Optional[str]
    icon: Optional[str]
    color: Optional[str]
    creator: Optional[dict[str, Any]]
    action: ReferenceAction

    @classmethod
    def from_result(cls, result: dict[str, Any]) -> "GenerationReferenceRecord":
        generation = result.get("generation") or {}
        kind = generation.get("kind")
        return cls(
            uid=result["uid"],
            created_at=format_datetime(result["created_at"]),
            name=result["name"],
            path=format_udin_url(result["path"]),
            size=format_size(result["size"]),
            version=result["version"],
            kind=kind,
            prompt=generation.get("prompt"),
            full_prompt=generation.get("full_prompt"),
            model=(generation.get("model_option") or {}).get("name"),
            icon=GENERATION_KIND_ICON_COLOR.get(kind, {}).get("icon"),  # type: ignore
            color=GENERATION_KIND_ICON_COLOR.get(kind, {}).get("color"),  # type: ignore
            creator=format_user_employees(result.get("created_by_user")),
            action=ReferenceAction.from_result(result["path"]),
        )


class UploadedReferenceRecord(BaseModel):
    type: str = "upload"
    uid: Any
    created_at: Optional[str]
    name: str
    path: str
    size: str
    kind: Optional[str]
    icon: Optional[str]
    color: Optional[str]
    uploader: Optional[dict[str, Any]]
    action: ReferenceAction

    @classmethod
    def from_result(cls, file: dict[str, Any]) -> "UploadedReferenceRecord":
        return cls(
            uid=file["uid"],
            created_at=format_datetime(file["created_at"]),
            name=file["name"],
            path=format_udin_url(file["path"]),
            size=format_size(file["size"]),
            kind=file["type"],
            icon=UPLOAD_TYPE_ICON_COLOR.get(file["type"], {}).get("icon"),
            color=UPLOAD_TYPE_ICON_COLOR.get(file["type"], {}).get("color"),
            uploader=format_user_employees(file.get("created_by_user")),
            action=ReferenceAction.from_result(file["path"]),
        )


class UploadedFileRecord(BaseModel):
    id: Optional[int] = None
    created_at: Optional[str]
    updated_at: Optional[str]
    file_uid: Any
    name: str
    kind: Optional[str]
    path: str
    size: str
    icon: Optional[str]
    color: Optional[str]
    creator: Optional[dict[str, Any]]
    updater: Optional[dict[str, Any]]

    @classmethod
    def from_result(cls, result: dict[str, Any]) -> "UploadedFileRecord":
        return cls(
            id=result.get("id"),
            created_at=format_datetime(result["created_at"]),
            updated_at=format_datetime(result.get("updated_at")),
            file_uid=result["uid"],
            name=result["name"],
            kind=result["type"],
            path=format_udin_url(result["path"]),
            size=format_size(result["size"]),
            icon=UPLOAD_TYPE_ICON_COLOR.get(result["type"], {}).get("icon"),
            color=UPLOAD_TYPE_ICON_COLOR.get(result["type"], {}).get("color"),
            creator=format_user_employees(result.get("created_by_user")),
            updater=format_user_employees(result.get("updated_by_user")),
        )


class FeatureableAction(BaseModel):
    can_fetch_detail: bool
    can_update: bool
    can_delete: bool

    @classmethod
    def from_result(
        cls, result: dict[str, Any], user_id: Optional[int] = None, is_referenced: bool = False
    ) -> "FeatureableAction":
        is_owner = user_id is not None and result.get("created_by") == user_id
        return cls(can_fetch_detail=is_owner, can_update=is_owner, can_delete=is_owner and not is_referenced)


class BaseNamedRecord(BaseModel):
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    icon: Optional[str] = None
    uid: Optional[Any] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    creator: Optional[dict[str, Any]] = None
    updater: Optional[dict[str, Any]] = None
    action: Optional[FeatureableAction] = None

    @classmethod
    def _base_fields(cls, result: dict[str, Any], action: Optional[FeatureableAction]) -> dict[str, Any]:
        return dict(
            created_at=format_datetime(result.get("created_at")),
            updated_at=format_datetime(result.get("updated_at")),
            icon=result.get("icon"),
            uid=result.get("uid"),
            name=result.get("name"),
            description=result.get("description"),
            is_active=result.get("is_active"),
            creator=format_user_employees(result.get("created_by_user")),
            updater=format_user_employees(result.get("updated_by_user")),
            action=action,
        )


class PromptTemplateRecord(BaseNamedRecord):
    prompt: Optional[str] = None

    @classmethod
    def from_result(
        cls, result: dict[str, Any], feature_id: Optional[int] = None, action: Optional[FeatureableAction] = None
    ) -> "PromptTemplateRecord":
        return cls(**cls._base_fields(result, action), prompt=result.get("prompt"))


class FeatureRecord(BaseNamedRecord):
    id: Optional[int] = None
    prompt_templates: list[PromptTemplateRecord] = []

    @classmethod
    def from_result(
        cls,
        result: dict[str, Any],
        prompt_templates: list[PromptTemplateRecord],
        action: Optional[FeatureableAction] = None,
    ) -> "FeatureRecord":
        return cls(**cls._base_fields(result, action), id=result.get("id"), prompt_templates=prompt_templates)


class MenuRecord(BaseNamedRecord):
    id: Optional[int] = None
    features: list[FeatureRecord] = []

    @classmethod
    def from_result(
        cls, result: dict[str, Any], features: list[FeatureRecord], action: Optional[FeatureableAction] = None
    ) -> "MenuRecord":
        return cls(**cls._base_fields(result, action), id=result.get("id"), features=features)


class FolderAction(BaseModel):
    can_rename: bool = False
    can_create_subfolder: bool = False
    can_delete: bool = False
    can_choose_to_move: bool = False
    can_receive_move: bool = False


class FileAction(BaseModel):
    can_rename: bool = False
    can_delete: bool = False
    can_choose_to_move: bool = False
    can_use_as_reference: bool = True


class TreeFile(BaseModel):
    file_uid: Optional[Any] = None
    name: str
    path: str
    url: str
    kind: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    created_at: Optional[str] = None
    creator: Optional[dict[str, Any]] = None
    action: Union[GenerationAction, FileAction]


class TreeFolder(BaseModel):
    name: str
    path: str
    kind: Literal["folder"] = "folder"
    icon: str = UPLOAD_TYPE_ICON_COLOR[UploadFileTypes.folder]["icon"]
    color: str = UPLOAD_TYPE_ICON_COLOR[UploadFileTypes.folder]["color"]
    action: FolderAction
    creator: Optional[dict[str, Any]] = None
    updater: Optional[dict[str, Any]] = None
    files: list[TreeFile] = []
    children: list["TreeFolder"] = []
