from datetime import datetime
from decimal import Decimal
from functools import cached_property
from typing import Any, Optional, Union
from sqlalchemy import Boolean, Column, DateTime, DECIMAL, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import object_session, selectinload
from sqlmodel import Field, Relationship, SQLModel
from services.mysql.model.df_engine_api_key_snapshots import DfEngineApiKeySnapshots
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from services.mysql.model.df_engine_feature_snapshots import DfEngineFeatureSnapshots
from services.mysql.model.df_engine_features import DfEngineFeatures
from utils import local_time


class DfEnginePromptEnhancers(SQLModel, table=True):
    __tablename__ = "df_engine_prompt_enhancers"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    model_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_model_options.id"), nullable=False)
    )
    featureable_id: int = Field(sa_column=Column(BIGINT(unsigned=True), nullable=False))
    featureable_type: str = Field(sa_column=Column(String(255), nullable=False))
    sourceable_id: int = Field(sa_column=Column(BIGINT(unsigned=True), nullable=False))
    sourceable_type: str = Field(sa_column=Column(String(255), nullable=False))
    project_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=True)
    )
    task_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("project_tasks.id"), nullable=True)
    )
    raw: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    enhanced: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    is_processing: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    response: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    status_code: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    token_usage: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    cost: Decimal = Field(default=Decimal("0.00"), sa_column=Column(DECIMAL(10, 2), nullable=False))
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )

    model_option: Optional["DfEngineModelOptions"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DfEnginePromptEnhancers.model_id]"}
    )  # type: ignore
    project: Optional["Projects"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DfEnginePromptEnhancers.project_id]"}
    )  # type: ignore
    task: Optional["ProjectTasks"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DfEnginePromptEnhancers.task_id]"}
    )  # type: ignore
    created_by_user: Optional["Users"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DfEnginePromptEnhancers.created_by]"}
    )  # type: ignore

    @property
    def is_api_key(self) -> bool:
        return self.sourceable_type == DfEngineApiKeys.__name__

    @property
    def is_api_key_snapshot(self) -> bool:
        return self.sourceable_type == DfEngineApiKeySnapshots.__name__

    def validate_sourceable_type(self) -> None:
        if not (self.is_api_key or self.is_api_key_snapshot):
            raise ValueError(f"Unsupported sourceable_type: {self.sourceable_type!r}")

    @cached_property
    def sourceable(self) -> Optional[Union[DfEngineApiKeys, DfEngineApiKeySnapshots]]:
        """Resolves `sourceable_id`/`sourceable_type` to the real row it points
        at — usable like any other relation attribute (`row.sourceable`). Reads
        via `object_session(self)`, the plain sync Session this row is already
        bound to — from async code, `serialize()` handles running that inside
        `AsyncSession.run_sync`.
        """
        self.validate_sourceable_type()
        session = object_session(self)
        if session is None:
            return None
        target_class = DfEngineApiKeys if self.is_api_key else DfEngineApiKeySnapshots
        return session.get(target_class, self.sourceable_id)

    @property
    def is_feature(self) -> bool:
        return self.featureable_type == DfEngineFeatures.__name__

    @property
    def is_feature_snapshot(self) -> bool:
        return self.featureable_type == DfEngineFeatureSnapshots.__name__

    def validate_featureable_type(self) -> None:
        if not (self.is_feature or self.is_feature_snapshot):
            raise ValueError(f"Unsupported featureable_type: {self.featureable_type!r}")

    @cached_property
    def featureable(self) -> Optional[Union[DfEngineFeatures, DfEngineFeatureSnapshots]]:
        self.validate_featureable_type()
        session = object_session(self)
        if session is None:
            return None
        if self.is_feature:
            return session.get(DfEngineFeatures, self.featureable_id)
        return session.get(
            DfEngineFeatureSnapshots,
            self.featureable_id,
            options=(selectinload(DfEngineFeatureSnapshots.df_engine_prompt_template_snapshots),),  # type: ignore
            populate_existing=True,
        )
