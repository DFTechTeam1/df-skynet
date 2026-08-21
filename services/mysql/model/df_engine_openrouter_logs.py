from datetime import datetime
from typing import Any, Optional
from uuid import uuid4
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import CHAR, DateTime, Integer, JSON, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineOpenrouterLogs(SQLModel, table=True):
    __tablename__ = "df_engine_openrouter_logs"  # type: ignore

    id: int = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    )
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    method: str = Field(sa_column=Column(String(10), nullable=False))
    endpoint: str = Field(sa_column=Column(String(255), nullable=False))
    request_headers: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    request_payload: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    response_status_code: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    response_headers: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    response_body: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    duration_ms: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
