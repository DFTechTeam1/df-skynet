from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import CHAR, DateTime, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineApiKeyRotationIssues(SQLModel, table=True):
    __tablename__ = "df_engine_api_key_rotation_issues"  # type: ignore

    id: int = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    )
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    old_uid: str = Field(sa_column=Column(CHAR(36), nullable=False))
    new_uid: Optional[str] = Field(default=None, sa_column=Column(CHAR(36), nullable=True))
    new_key_hash: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    new_key_value: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    issue_type: str = Field(sa_column=Column(String(50), nullable=False))
    detail: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    resolved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
