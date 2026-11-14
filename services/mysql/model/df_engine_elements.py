from datetime import datetime
from enum import StrEnum, auto
from typing import Any, Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DateTime, Enum, ForeignKey, String, and_
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT
from sqlalchemy.orm import foreign
from services.mysql.model.df_engine_element_uploads import DfEngineElementUploads
from services.mysql.model.df_engine_generation_results import DfEngineGenerationResults
from utils import local_time


class ElementTypes(StrEnum):
    environment = auto()
    character = auto()
    object = auto()
    style = auto()


class DfEngineElements(SQLModel, table=True):
    __tablename__ = "df_engine_elements"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True, onupdate=local_time))
    type: ElementTypes = Field(sa_column=Column(Enum(ElementTypes), nullable=False))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT, nullable=True))
    task_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("project_tasks.id", ondelete="SET NULL"), nullable=True),
    )
    song_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("project_song_lists.id", ondelete="SET NULL"), nullable=True
        ),
    )
    project_id: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=True)
    )
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )
    updated_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True)
    )
    sourceable_id: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), nullable=True))
    sourceable_type: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))

    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineElements.created_by]"}
    )
    updated_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineElements.updated_by]"}
    )
    generations: list["DfEngineElementGenerations"] = Relationship(  # type: ignore
        back_populates="element"
    )
    uploads: list["DfEngineElementUploads"] = Relationship(  # type: ignore
        back_populates="element"
    )
    project: Optional["Projects"] = Relationship(back_populates="df_engine_elements")  # type: ignore

    source_generation_result: Optional["DfEngineGenerationResults"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineElements.sourceable_id) == DfEngineGenerationResults.id,  # type: ignore
                DfEngineElements.sourceable_type == DfEngineGenerationResults.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )
    source_upload: Optional["DfEngineElementUploads"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineElements.sourceable_id) == DfEngineElementUploads.id,  # type: ignore
                DfEngineElements.sourceable_type == DfEngineElementUploads.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )

    @property
    def sourceable(self) -> Optional[Any]:
        """The resolved `source_generation_result`/`source_upload`, whichever `sourceable_type` points at.
        Requires that relationship to already be loaded (e.g. via `selectinload`)."""
        if self.sourceable_type == DfEngineGenerationResults.__name__:
            return self.source_generation_result
        if self.sourceable_type == DfEngineElementUploads.__name__:
            return self.source_upload
        return None
