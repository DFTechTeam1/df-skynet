from decimal import Decimal
from typing import Any, Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DECIMAL, ForeignKey, JSON
from sqlalchemy.dialects.mysql import BIGINT


class DfEngineImageGenerationDetails(SQLModel, table=True):
    __tablename__ = "df_engine_image_generation_details"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    enhancer_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=True)
    )
    parameter: Optional[dict[str, Any]] = Field(
        default_factory=dict, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    x_min: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2), nullable=True))
    x_max: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2), nullable=True))
    y_min: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2), nullable=True))
    y_max: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2), nullable=True))

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineImageGenerationDetails.generation_id]"}
    )
    enhancer: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineImageGenerationDetails.enhancer_id]"}
    )
