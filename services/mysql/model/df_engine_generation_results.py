from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import BigInteger, Boolean, CHAR, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineGenerationResults(SQLModel, table=True):
    __tablename__ = "df_engine_generation_results"  # type: ignore
    __table_args__ = (
        Index("idx_generation_results_generation_id", "generation_id"),
        Index("idx_generation_results_parent_id", "parent_id"),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    archieved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    generation_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=True)
    )
    parent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generation_results.id"), nullable=True),
    )
    md5: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    path: str = Field(sa_column=Column(Text, nullable=False))
    size: int = Field(sa_column=Column(BigInteger, nullable=False))
    is_main: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    is_favourite: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )
    updated_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationResults.generation_id]"}
    )
    parent: Optional["DfEngineGenerationResults"] = Relationship(  # type: ignore
        sa_relationship_kwargs={
            "foreign_keys": "[DfEngineGenerationResults.parent_id]",
            "remote_side": "[DfEngineGenerationResults.id]",
        }
    )
    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationResults.created_by]"}
    )
    updated_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineGenerationResults.updated_by]"}
    )
