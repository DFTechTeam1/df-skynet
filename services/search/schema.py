from pydantic import BaseModel, Field
from typing import Optional, Any


class FileTreeNode(BaseModel):
    objectID: str = Field(..., description="The unique identifier of the file or directory.")
    file_uid: str = Field(..., description="The unique identifier of the file or directory in the system.")
    name: str = Field(..., description="The name of the file or directory.")
    path: str = Field(..., description="The path of the file or directory.")
    creator: Optional[dict[str, Any]] = Field(None, description="The creator of the file or directory.")
    updater: Optional[dict[str, Any]] = Field(None, description="The last updater of the file or directory.")
