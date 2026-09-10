from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineGenerationReferences(SQLModel, table=True):
    __tablename__ = "df_engine_generation_references"  # type: ignore
    __table_args__ = (
        Index("idx_generation_references_generation_id", "generation_id"),
        Index("idx_generation_references_result_id", "result_id"),
        Index("idx_generation_references_unique_pair", "generation_id", "result_id", unique=True),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    result_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generation_results.id"), nullable=False)
    )

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationReferences.generation_id]"}
    )
    result: Optional["DfEngineGenerationResults"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationReferences.result_id]"}
    )
