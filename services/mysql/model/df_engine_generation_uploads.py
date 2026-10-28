from datetime import datetime
from enum import StrEnum, auto
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class UploadStatuses(StrEnum):
    pending = auto()
    success = auto()
    failed = auto()


class DfEngineGenerationUploads(SQLModel, table=True):
    __tablename__ = "df_engine_generation_uploads"  # type: ignore
    __table_args__ = (
        Index("idx_generation_uploads_generation_id", "generation_id", unique=True),
        Index("idx_generation_uploads_status_uploaded_at", "upload_status", "uploaded_at"),
        Index("idx_generation_uploads_needs_reconciliation", "needs_reconciliation"),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    uploaded_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    upload_status: UploadStatuses = Field(
        default=UploadStatuses.pending, sa_column=Column(Enum(UploadStatuses), nullable=False)
    )
    sweep_attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    needs_reconciliation: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    reconciled_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationUploads.generation_id]"}
    )
