from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID


class Attachment(BaseModel):
    file_uid: UUID = Field(...)
    type: Literal["upload", "generated"] = Field(
        ...
    )  # upload will pointing to df_engine_upload_files, and generated will pointing to df_engine_generation_results
