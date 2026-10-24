from pydantic import BaseModel
from typing import Any


class FolderAction(BaseModel):
    can_rename: bool = False
    can_create_subfolder: bool = False
    can_delete: bool = False
    can_choose_to_move: bool = False
    can_receive_move: bool = False
    can_upload_file: bool = True

    @classmethod
    def action(cls, is_owner: bool, can_override: bool, path: str, depth_limit: int) -> "FolderAction":
        """`path` = storage/<root>/<project>/<upload|generated>/<images|videos>/<subfolders...>.
        The type root (5 segments) is fixed; only subfolders below it can be renamed/deleted/moved, and a folder
        takes another subfolder only while its chain is under the admin `folder_depth_limit`."""
        allowed = is_owner or can_override
        chain = len(path.split("/")) - 5  # subfolder levels below the type root
        can_nest = 0 <= chain < depth_limit
        mutable = allowed and chain >= 1
        return cls(
            can_rename=mutable,
            can_create_subfolder=can_nest,
            can_delete=mutable,
            can_choose_to_move=mutable,
            can_receive_move=can_nest,
        )


class UploadedFileAction(BaseModel):
    can_rename: bool = False
    can_delete: bool = False
    can_choose_to_move: bool = False
    can_use_as_reference: bool = True
    can_download: bool = True

    @classmethod
    def action(cls, is_owner: bool, can_override: bool) -> "UploadedFileAction":
        allowed = is_owner or can_override
        return cls(can_rename=allowed, can_delete=allowed, can_choose_to_move=allowed)


class FailedUploadAction(BaseModel):
    can_reupload: bool = True  # false while a sweep or manual upload holds the generation's re-upload lock


class GeneratedFileAction(BaseModel):
    can_set_archieve: bool = True
    can_set_main: bool = False
    can_set_favorite: bool = True
    can_fetch_detail: bool = True
    can_use_as_edit: bool = True
    can_rename: bool = False
    can_choose_to_move: bool = False
    can_use_as_reference: bool = True
    can_download: bool = True

    @classmethod
    def disabled(cls) -> "GeneratedFileAction":
        return cls(**dict.fromkeys(cls.model_fields, False))

    @classmethod
    def action(cls, is_owner: bool, can_override: bool, record: dict[str, Any]) -> "GeneratedFileAction":
        allowed = is_owner or can_override
        archived = record.get("archieved_at") is not None
        favorited = bool(record.get("favourites")) or record.get("favourited_at") is not None  # the viewer's own
        is_video = "/videos/" in record["path"]
        return cls(
            can_set_archieve=is_owner and not archived and not record["is_main"],
            can_set_main=allowed and not record["is_main"],
            can_set_favorite=not favorited,
            can_use_as_reference=not is_video,
            can_use_as_edit=allowed and not is_video,
            can_rename=allowed,
            can_choose_to_move=allowed and not archived,
        )
