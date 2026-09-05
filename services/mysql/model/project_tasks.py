from datetime import date, datetime
from enum import StrEnum, auto
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DateTime, Date, Enum, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.mysql import BIGINT


class ProjectTaskTypes(StrEnum):
    asset3d = auto()
    compositing = auto()
    animating = auto()
    finalize = auto()


class ProjectTasks(SQLModel, table=True):
    __tablename__ = "project_tasks"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(sa_column=Column(CHAR(36), nullable=False))
    project_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False))
    project_board_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("project_boards.id"), nullable=False)
    )
    start_date: Optional[date] = Field(default=None, sa_column=Column(Date, nullable=True))
    end_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    start_working_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    created_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    updated_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    task_type: Optional[ProjectTaskTypes] = Field(default=None, sa_column=Column(Enum(ProjectTaskTypes), nullable=True))
    performance_time: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: Optional[int] = Field(default=None, sa_column=Column(SmallInteger, nullable=True))
    current_pics: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    current_board: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    is_approved: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False))
    task_identifier_id: Optional[str] = Field(default=None, sa_column=Column(String(4), nullable=True, unique=True))
    is_modeler_task: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False))
    is_pool_task: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False))
    is_pool_type: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False))

    project: Optional["Projects"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[ProjectTasks.project_id]"}
    )
