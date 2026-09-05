from datetime import datetime
from typing import Any, Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineFeatureSnapshots(SQLModel, table=True):
    __tablename__ = "df_engine_feature_snapshots"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )
    updated_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )

    df_engine_prompt_template_snapshots: list["DfEnginePromptTemplateSnapshots"] = Relationship(  # type: ignore
        back_populates="feature_snapshot"
    )
