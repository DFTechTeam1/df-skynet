from sqlmodel import Column, Field, SQLModel
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.mysql import BIGINT


class DfEngineElementGenerations(SQLModel, table=True):
    __tablename__ = "df_engine_element_generations"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    element_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_elements.id"), nullable=False)
    )
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
