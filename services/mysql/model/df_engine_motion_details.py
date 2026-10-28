from datetime import datetime
from enum import StrEnum, auto
from typing import Any, Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, Enum, ForeignKey, Index, JSON
from sqlalchemy.dialects.mysql import BIGINT


class Motions(StrEnum):
    static = auto()
    pan = auto()
    tilt = auto()
    push_in = auto()
    pull_back = auto()
    track = auto()
    crane = auto()
    handheld = auto()


class DfEngineMotionDetails(SQLModel, table=True):
    __tablename__ = "df_engine_motion_details"  # type: ignore
    __table_args__ = (Index("idx_motion_details_shot_id", "shot_id"),)

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    archieved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    shot_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_scene_shots.id"), nullable=False)
    )
    motion: Optional[Motions] = Field(default=Motions.static, sa_column=Column(Enum(Motions), nullable=True))
    parameter: Optional[dict[str, Any]] = Field(
        default_factory=dict, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineMotionDetails.generation_id]"}
    )
    shot: Optional["DfEngineSceneShots"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineMotionDetails.shot_id]"}
    )
