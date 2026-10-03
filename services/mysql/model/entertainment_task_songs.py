from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.mysql import BIGINT, TINYINT

SONG_STATUS_ACTIVE = 1
SONG_STATUS_ON_PROGRESS = 2
SONG_STATUS_REVISE = 3
SONG_STATUS_ON_FIRST_REVIEW = 4
SONG_STATUS_ON_LAST_REVIEW = 5
SONG_STATUS_COMPLETED = 6


class EntertainmentTaskSongs(SQLModel, table=True):
    __tablename__ = "entertainment_task_songs"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    project_song_list_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("project_song_lists.id"), nullable=False)
    )
    status: int = Field(sa_column=Column(TINYINT, nullable=False))
    employee_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("employees.id"), nullable=False))
    project_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False))
    time_tracker: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
