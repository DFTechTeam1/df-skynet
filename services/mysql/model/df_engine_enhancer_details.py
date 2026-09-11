from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.mysql import BIGINT


class DfEngineEnhancerDetails(SQLModel, table=True):
    __tablename__ = "df_engine_enhancer_details"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    raw: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    enhanced: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineEnhancerDetails.generation_id]"}
    )
