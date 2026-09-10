from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from functools import cached_property
from typing import Any, Optional, Union
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DECIMAL, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import object_session
from services.mysql.model.df_engine_api_key_snapshots import DfEngineApiKeySnapshots
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from utils import local_time


class GenerationKinds(StrEnum):
    image = auto()
    video = auto()
    element = auto()
    storyboard = auto()
    keyframe = auto()
    motion = auto()
    chat = auto()
    enhancer = auto()


class GenerationStatuses(StrEnum):
    queued = auto()
    processing = auto()
    success = auto()
    failed = auto()


class DfEngineGenerations(SQLModel, table=True):
    __tablename__ = "df_engine_generations"  # type: ignore
    __table_args__ = (
        Index("idx_generations_kind", "kind"),
        Index("idx_generations_kind_created_by", "kind", "created_by"),
        Index("idx_generations_project_task", "project_id", "task_id"),
        Index("idx_generations_created_by", "created_by"),
        Index("idx_generations_status_created_at", "status", "created_at"),
        Index("idx_generations_sourceable", "sourceable_id", "sourceable_type"),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    kind: GenerationKinds = Field(sa_column=Column(Enum(GenerationKinds), nullable=False))
    model_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_model_options.id"), nullable=False)
    )
    menu_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_menus.id"), nullable=False))
    feature_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_features.id"), nullable=False)
    )
    sourceable_id: int = Field(sa_column=Column(BIGINT(unsigned=True), nullable=False))
    sourceable_type: str = Field(sa_column=Column(String(255), nullable=False))
    project_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=True)
    )
    task_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("project_tasks.id"), nullable=True)
    )
    prompt: str = Field(sa_column=Column(Text, nullable=False))
    status: GenerationStatuses = Field(
        default=GenerationStatuses.processing, sa_column=Column(Enum(GenerationStatuses), nullable=False)
    )
    response: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON(none_as_null=True), nullable=True))
    status_code: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    token_usage: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    cost: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2), nullable=True))
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )

    model_option: Optional["DfEngineModelOptions"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerations.model_id]"}
    )
    menu: Optional["DfEngineMenus"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerations.menu_id]"}
    )
    feature: Optional["DfEngineFeatures"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerations.feature_id]"}
    )
    project: Optional["Projects"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerations.project_id]"}
    )
    task: Optional["ProjectTasks"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerations.task_id]"}
    )
    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerations.created_by]"}
    )

    @property
    def is_api_key(self) -> bool:
        return self.sourceable_type == DfEngineApiKeys.__name__

    @property
    def is_api_key_snapshot(self) -> bool:
        return self.sourceable_type == DfEngineApiKeySnapshots.__name__

    def validate_sourceable_type(self) -> None:
        if not (self.is_api_key or self.is_api_key_snapshot):
            raise ValueError(f"Unsupported sourceable_type: {self.sourceable_type!r}")

    @cached_property
    def sourceable(self) -> Optional[Union[DfEngineApiKeys, DfEngineApiKeySnapshots]]:
        self.validate_sourceable_type()
        session = object_session(self)
        if session is None:
            return None
        target_class = DfEngineApiKeys if self.is_api_key else DfEngineApiKeySnapshots
        return session.get(target_class, self.sourceable_id)
