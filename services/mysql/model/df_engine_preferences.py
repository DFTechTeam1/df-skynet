from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, DECIMAL, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEnginePreferences(SQLModel, table=True):
    __tablename__ = "df_engine_preferences"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    user_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False, unique=True))
    theme: str = Field(default="dark", sa_column=Column(String(20), nullable=False))
    accent: str = Field(default="teal", sa_column=Column(String(20), nullable=False))
    language: str = Field(default="english", sa_column=Column(String(20), nullable=False))
    default_aspect_ratio: str = Field(default="16:9", sa_column=Column(String(20), nullable=False))
    default_size: str = Field(default="4K", sa_column=Column(String(20), nullable=False))
    confirm_before_spending: float = Field(default=0.50, sa_column=Column(DECIMAL(10, 2), nullable=False))

    users: Optional["Users"] = Relationship(  # type: ignore
        back_populates="df_engine_preferences", sa_relationship_kwargs={"uselist": False}
    )
