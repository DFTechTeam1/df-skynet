from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT


class DfEngineChatDetails(SQLModel, table=True):
    __tablename__ = "df_engine_chat_details"  # type: ignore
    __table_args__ = (Index("idx_chat_details_parent_id", "parent_id"),)

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    parent_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=True)
    )

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineChatDetails.generation_id]"}
    )
    parent: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineChatDetails.parent_id]"}
    )
