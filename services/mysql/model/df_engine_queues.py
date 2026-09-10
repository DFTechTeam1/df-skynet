from datetime import datetime
from enum import StrEnum, auto
from typing import Any, Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class QueueEventTypes(StrEnum):
    enqueued = auto()
    started = auto()
    retried = auto()
    succeeded = auto()
    failed = auto()


class DfEngineQueues(SQLModel, table=True):
    __tablename__ = "df_engine_queues"  # type: ignore
    __table_args__ = (
        Index("idx_queues_task_uid", "task_uid"),
        Index("idx_queues_generation_event", "generation_id", "event_type"),
        Index("idx_queues_queue_event", "queue_name", "event_type"),
        Index("idx_queues_generation_created_at", "generation_id", "created_at"),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    task_uid: str = Field(sa_column=Column(String(36), nullable=False))
    generation_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=True)
    )
    queue_name: str = Field(sa_column=Column(String(255), nullable=False))
    event_type: QueueEventTypes = Field(sa_column=Column(Enum(QueueEventTypes), nullable=False))
    attempt: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    detail: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON(none_as_null=True), nullable=True))

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineQueues.generation_id]"}
    )
