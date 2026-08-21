from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import CHAR, DateTime, DECIMAL, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineApiSnapshots(SQLModel, table=True):
    __tablename__ = "df_engine_api_snapshots"  # type: ignore

    id: int = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    )
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    expired_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    limit: Optional[float] = Field(default=None, sa_column=Column(DECIMAL(10, 2), nullable=True))
    limit_reset: Optional[str] = Field(default=None, sa_column=Column(String(20), nullable=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    key: str = Field(sa_column=Column(String(255), nullable=False, unique=True))
    hash: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    employee_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    created_by: int = Field(sa_column=Column(BIGINT(unsigned=True), nullable=False))
    updated_by: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), nullable=True))
