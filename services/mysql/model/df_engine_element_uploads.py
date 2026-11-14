from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import BigInteger, CHAR, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineElementUploads(SQLModel, table=True):
    __tablename__ = "df_engine_element_uploads"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    path: str = Field(sa_column=Column(Text, nullable=False))
    md5: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    size: int = Field(sa_column=Column(BigInteger, nullable=False))
    element_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_elements.id"), nullable=False)
    )
    project_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False))
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )
    updated_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )

    element: Optional["DfEngineElements"] = Relationship(back_populates="uploads")  # type: ignore
    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineElementUploads.created_by]"}
    )
    updated_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineElementUploads.updated_by]"}
    )
    project: Optional["Projects"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineElementUploads.project_id]"}
    )
