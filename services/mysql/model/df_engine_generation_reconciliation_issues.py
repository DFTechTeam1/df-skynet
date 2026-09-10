from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineGenerationReconciliationIssues(SQLModel, table=True):
    __tablename__ = "df_engine_generation_reconciliation_issues"  # type: ignore
    __table_args__ = (
        Index("idx_reconciliation_issues_generation_id", "generation_id"),
        Index("idx_reconciliation_issues_unresolved", "resolved_at"),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    upload_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generation_uploads.id"), nullable=True),
    )
    issue_type: str = Field(sa_column=Column(String(50), nullable=False))
    detail: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    resolved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    resolved_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationReconciliationIssues.generation_id]"}
    )
    upload: Optional["DfEngineGenerationUploads"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationReconciliationIssues.upload_id]"}
    )
    resolved_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationReconciliationIssues.resolved_by]"}
    )
