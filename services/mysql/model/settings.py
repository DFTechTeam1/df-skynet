from utils import local_time
from datetime import datetime
from typing import Optional
from sqlalchemy import Text, String, DateTime
from sqlmodel import Column, Field, SQLModel
from sqlalchemy.dialects.mysql import BIGINT


class Settings(SQLModel, table=True):
    __tablename__ = "settings"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    key: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    value: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: Optional[datetime] = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    code: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
