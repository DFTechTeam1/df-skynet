from datetime import datetime
from enum import StrEnum, auto
from typing import Any, Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, Enum, ForeignKey, Index, JSON
from sqlalchemy.dialects.mysql import BIGINT


class ShotSizes(StrEnum):
    extreme_wide = auto()
    medium_wide = auto()
    wide = auto()
    medium = auto()
    medium_close_up = auto()
    close_up = auto()
    extreme_close_up = auto()
    insert = auto()


class Angels(StrEnum):
    eye_level = auto()
    low = auto()
    high = auto()
    ground_level = auto()
    knee_level = auto()
    hip_level = auto()
    over_the_shoulder = auto()
    overhead = auto()
    top_view = auto()
    aerial = auto()
    dutch = auto()
    pov = auto()


class FocalLengths(StrEnum):
    mm_14 = auto()
    mm_24 = auto()
    mm_35 = auto()
    mm_50 = auto()
    mm_85 = auto()
    mm_135 = auto()


class DfEngineKeyframeDetails(SQLModel, table=True):
    __tablename__ = "df_engine_keyframe_details"  # type: ignore
    __table_args__ = (Index("idx_keyframe_details_shot_id", "shot_id"),)

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    generation_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_generations.id"), nullable=False)
    )
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    archieved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    shot_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_scene_shots.id"), nullable=False)
    )
    shot_size: Optional[ShotSizes] = Field(
        default=ShotSizes.extreme_wide, sa_column=Column(Enum(ShotSizes), nullable=True)
    )
    angel: Optional[Angels] = Field(default=Angels.low, sa_column=Column(Enum(Angels), nullable=True))
    focal: Optional[FocalLengths] = Field(
        default=FocalLengths.mm_50, sa_column=Column(Enum(FocalLengths), nullable=True)
    )
    parameter: Optional[dict[str, Any]] = Field(
        default_factory=dict, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )

    generation: Optional["DfEngineGenerations"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineKeyframeDetails.generation_id]"}
    )
    shot: Optional["DfEngineSceneShots"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineKeyframeDetails.shot_id]"}
    )
