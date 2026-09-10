from datetime import date, datetime
from enum import StrEnum, auto
from typing import Any, Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class ModelUsageTypes(StrEnum):
    text = auto()
    image = auto()
    video = auto()


class DfEngineModelOptions(SQLModel, table=True):
    __tablename__ = "df_engine_model_options"  # type: ignore
    __table_args__ = (
        Index("idx_model_options_model_id", "model_id", "type", unique=True),
        CheckConstraint(
            "is_main = false OR is_enabled = true",
            name="ck_df_engine_model_options_is_main_requires_enabled",
        ),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    last_sync_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    created: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    model_id: str = Field(sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    architecture: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    type: ModelUsageTypes = Field(
        default=ModelUsageTypes.image, sa_column=Column(Enum(ModelUsageTypes), nullable=False)
    )
    is_main: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    is_enabled: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    is_available: bool = Field(default=False, sa_column=Column(Boolean, nullable=True))
    supported_parameters: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    default_parameters: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    supports_streaming: Optional[bool] = Field(default=None, sa_column=Column(Boolean, nullable=True))
    supported_resolutions: Optional[list[Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    supported_aspect_ratios: Optional[list[Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    supported_sizes: Optional[list[Any]] = Field(default=None, sa_column=Column(JSON(none_as_null=True), nullable=True))
    supported_durations: Optional[list[Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    supported_frame_images: Optional[list[Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    generate_audio: Optional[bool] = Field(default=None, sa_column=Column(Boolean, nullable=True))
    allowed_passthrough_parameters: Optional[list[str]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    pricing_skus: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    pricing: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON(none_as_null=True), nullable=True))
    top_provider: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
    knowledge_cutoff: Optional[date] = Field(default=None, sa_column=Column(Date, nullable=True))
    expiration_date: Optional[date] = Field(default=None, sa_column=Column(Date, nullable=True))
    deleted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    deleted_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )

    deleted_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineModelOptions.deleted_by]"}
    )
