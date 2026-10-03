from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT, CHAR


class ProjectSongLists(SQLModel, table=True):
    __tablename__ = "project_song_lists"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(sa_column=Column(CHAR(36), nullable=False))
    project_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    is_request_edit: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    is_request_delete: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    created_by: int = Field(sa_column=Column(BIGINT, nullable=False))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    target_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    reason: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
