from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.mysql import BIGINT


class DfEngineStoryboardDetails(SQLModel, table=True):
    __tablename__ = "df_engine_storyboard_details"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineStoryboardDetails.generation_id]"}
    )
