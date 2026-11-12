from datetime import datetime
from enum import StrEnum, auto
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import CHAR, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class ElementTypes(StrEnum):
    environment = auto()
    character = auto()
    object = auto()
    style = auto()


class DfEngineElements(SQLModel, table=True):
    __tablename__ = "df_engine_elements"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True, onupdate=local_time))
    types: Optional[ElementTypes] = Field(default=None, sa_column=Column(Enum(ElementTypes), nullable=True))
    prompt: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    task_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("project_tasks.id", ondelete="SET NULL"), nullable=True),
    )
    song_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("project_song_lists.id", ondelete="SET NULL"), nullable=True
        ),
    )
    project_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=True)
    )
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )
    updated_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )
