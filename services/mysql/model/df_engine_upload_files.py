from datetime import datetime
from enum import StrEnum, auto
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import BigInteger, CHAR, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class UploadFileTypes(StrEnum):
    video = auto()
    image = auto()


class DfEngineUploadFiles(SQLModel, table=True):
    __tablename__ = "df_engine_upload_files"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    type: UploadFileTypes = Field(
        default=UploadFileTypes.image, sa_column=Column(Enum(UploadFileTypes), nullable=False)
    )
    path: str = Field(sa_column=Column(Text, nullable=False))
    md5: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    size: int = Field(sa_column=Column(BigInteger, nullable=False))
    project_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False))
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )
    updated_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )

    project: Optional["Projects"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineUploadFiles.project_id]"}
    )
    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineUploadFiles.created_by]"}
    )
    updated_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineUploadFiles.updated_by]"}
    )
