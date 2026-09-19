from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from typing import Any, Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DECIMAL, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, and_
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import foreign
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
    image_edit = auto()


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
        Index("idx_generations_created_at", "created_at"),
        Index("idx_generations_task_created_by_created_at", "task_id", "created_by", "created_at"),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
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
    full_prompt: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
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
    result: Optional["DfEngineGenerationResults"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationResults.generation_id]", "viewonly": True}
    )

    api_key: Optional["DfEngineApiKeys"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineGenerations.sourceable_id) == DfEngineApiKeys.id,  # type: ignore
                DfEngineGenerations.sourceable_type == DfEngineApiKeys.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )
    api_key_snapshot: Optional["DfEngineApiKeySnapshots"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineGenerations.sourceable_id) == DfEngineApiKeySnapshots.id,  # type: ignore
                DfEngineGenerations.sourceable_type == DfEngineApiKeySnapshots.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )

    @property
    def sourceable(self) -> Optional[Any]:
        """The resolved `api_key`/`api_key_snapshot`, whichever `sourceable_type` points at.
        Requires that relationship to already be loaded (e.g. via `selectinload`)."""
        return self.api_key if self.sourceable_type == DfEngineApiKeys.__name__ else self.api_key_snapshot
