from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DateTime, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineChatSessions(SQLModel, table=True):
    __tablename__ = "df_engine_chat_sessions"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    archieved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    topic: str = Field(sa_column=Column(String(255), nullable=False))
    menu_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_menus.id"), nullable=False))
    feature_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_features.id"), nullable=False)
    )
    project_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False))
    created_by: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False))

    chat_assistants: list["DfEngineChatAssistants"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"order_by": "DfEngineChatAssistants.id"}
    )
