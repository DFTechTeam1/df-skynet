from datetime import datetime
from typing import Any, Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineSettingLogs(SQLModel, table=True):
    __tablename__ = "df_engine_setting_logs"  # type: ignore

    id: int = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    )
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_by: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False))
    user_email: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    user_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    previous_data: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    incoming_data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    ip_address: Optional[str] = Field(default=None, sa_column=Column(String(45), nullable=True))
    user_agent: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))

    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineSettingLogs.created_by]"}
    )
