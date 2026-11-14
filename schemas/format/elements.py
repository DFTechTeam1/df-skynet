from schemas.format.base import TimeframeMeta, UserMeta, ImageMeta
from pydantic import BaseModel, Field, ValidationInfo, model_validator
from typing import Optional
from static.icon import element_type_icons


class ElementFileAction(BaseModel):
    can_edit: bool = True
    can_rename: bool = True


class ElementAction(BaseModel):
    can_delete: bool = True
    can_fetch: bool = True
    can_update: bool = True
    can_generate: bool = True


class ElementImage(ImageMeta):
    action: ElementFileAction = Field(default_factory=ElementFileAction)

    @model_validator(mode="after")
    def format_action(self, info: ValidationInfo):
        viewer_id = (info.context or {}).get("user_id")
        creator_id = (self.creator or {}).get("user_id")
        is_creator = viewer_id is not None and creator_id is not None and int(viewer_id) == int(creator_id)
        can_manage = is_creator or bool((info.context or {}).get("is_overrider"))
        self.action = ElementFileAction(
            can_rename=is_creator,
            can_edit=can_manage,
        )
        return self


class Element(TimeframeMeta, UserMeta):
    uid: str
    name: str
    type: str
    description: Optional[str] = None
    action: ElementAction = Field(default_factory=ElementAction)
    main_image: Optional[ElementImage] = None
    images: Optional[list[ElementImage]] = None
    icon: Optional[str] = None
    color: Optional[str] = None

    @model_validator(mode="after")
    def format_icon_color(self):
        meta = element_type_icons.get(self.type) or {}
        self.icon = self.icon or meta.get("icon")
        self.color = self.color or meta.get("color")
        return self

    @model_validator(mode="after")
    def format_action(self, info: ValidationInfo):
        viewer_id = (info.context or {}).get("user_id")
        creator_id = (self.creator or {}).get("user_id")
        is_creator = viewer_id is not None and creator_id is not None and int(viewer_id) == int(creator_id)
        can_manage = is_creator or bool((info.context or {}).get("is_overrider"))
        self.action = ElementAction(
            can_fetch=True,
            can_update=can_manage,
            can_delete=can_manage and self.main_image is None,
            can_generate=can_manage,
        )
        return self
