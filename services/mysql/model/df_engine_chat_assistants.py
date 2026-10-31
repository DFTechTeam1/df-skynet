from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineChatAssistants(SQLModel, table=True):
    __tablename__ = "df_engine_chat_assistants"  # type: ignore
    __table_args__ = (Index("idx_chat_assistants_created_by_archived_at", "created_by", "archived_at"),)

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    placeholder: str = Field(sa_column=Column(Text(length=4294967295), nullable=False))
    created_by: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    archived_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
