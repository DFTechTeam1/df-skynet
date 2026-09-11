from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineUploadFileReferences(SQLModel, table=True):
    __tablename__ = "df_engine_upload_file_references"  # type: ignore
    __table_args__ = (
        Index("idx_upload_file_references_generation_id", "generation_id"),
        Index("idx_upload_file_references_file_id", "file_id"),
        Index("idx_upload_file_references_unique_pair", "generation_id", "file_id", unique=True),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    file_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_upload_files.id"), nullable=False)
    )

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineUploadFileReferences.generation_id]"}
    )
    file: Optional["DfEngineUploadFiles"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineUploadFileReferences.file_id]"}
    )
