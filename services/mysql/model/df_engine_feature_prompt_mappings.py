from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DateTime, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineFeaturePromptMappings(SQLModel, table=True):
    __tablename__ = "df_engine_feature_prompt_mappings"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    feature_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_features.id"), nullable=False)
    )
    template_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True),
            ForeignKey("df_engine_prompt_templates.id"),
            nullable=False,
        )
    )

    df_engine_features: Optional["DfEngineFeatures"] = Relationship(  # type: ignore
        back_populates="df_engine_feature_prompt_mappings"
    )
    df_engine_prompt_templates: Optional["DfEnginePromptTemplates"] = Relationship(  # type: ignore
        back_populates="df_engine_feature_prompt_mappings"
    )
