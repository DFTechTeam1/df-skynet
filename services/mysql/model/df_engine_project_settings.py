from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineProjectSettings(SQLModel, table=True):
    __tablename__ = "df_engine_project_settings"  # type: ignore

    id: int = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    )
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True, onupdate=local_time),
    )
    project_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False),
    )
    token_usage_limit: int = Field(sa_column=Column(Integer, nullable=False))
    concurent_generations: int = Field(sa_column=Column(Integer, nullable=False))
    compose_input_max_chars: int = Field(sa_column=Column(Integer, nullable=False))
    storyboard_prompt_chars: int = Field(sa_column=Column(Integer, nullable=False))
    max_scene_per_storyboard: int = Field(sa_column=Column(Integer, nullable=False))
    max_shot_per_scene: int = Field(sa_column=Column(Integer, nullable=False))
    created_by: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True),
    )
    updated_by: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True),
    )

    project: Optional["Projects"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineProjectSettings.project_id]"}
    )
    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineProjectSettings.created_by]"}
    )
    updated_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineProjectSettings.updated_by]"}
    )
