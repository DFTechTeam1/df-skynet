from datetime import datetime
from enum import StrEnum, auto
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class InteriorStyles(StrEnum):
    interior = auto()
    exterior = auto()
    interior_exterior = auto()


class TimeOfDays(StrEnum):
    pre_dawn = auto()
    sunrise = auto()
    morning = auto()
    midday = auto()
    afternoon = auto()
    golden_hour = auto()
    dusk = auto()
    blue_hour = auto()
    night = auto()


class LightingMoods(StrEnum):
    natural = auto()
    soft_diffused = auto()
    hard_high_contrast = auto()
    warm_practical = auto()
    moody_low_key = auto()
    high_key_bright = auto()
    silhouette_backlit = auto()
    neon = auto()
    overcast_flat = auto()


class DfEngineSceneShots(SQLModel, table=True):
    __tablename__ = "df_engine_scene_shots"  # type: ignore
    __table_args__ = (Index("idx_scene_shots_scene_id", "scene_id"),)

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    archieved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    scene_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_storyboard_scenes.id"), nullable=False)
    )
    name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    interior_style: Optional[InteriorStyles] = Field(
        default=InteriorStyles.interior, sa_column=Column(Enum(InteriorStyles), nullable=True)
    )
    time_of_day: Optional[TimeOfDays] = Field(
        default=TimeOfDays.sunrise, sa_column=Column(Enum(TimeOfDays), nullable=True)
    )
    lighting_mood: Optional[LightingMoods] = Field(
        default=LightingMoods.natural, sa_column=Column(Enum(LightingMoods), nullable=True)
    )

    scene: Optional["DfEngineStoryboardScenes"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineSceneShots.scene_id]"}
    )
