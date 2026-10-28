from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT


class ProjectTaskPics(SQLModel, table=True):
    __tablename__ = "project_task_pics"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    project_task_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("project_tasks.id"), nullable=False)
    )
    employee_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("employees.id"), nullable=False))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    status: Optional[str] = Field(default=None, sa_column=Column(String(1), nullable=True))
    assigned_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    assigned_by: Optional[int] = Field(
        default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("employees.id"), nullable=True)
    )
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
