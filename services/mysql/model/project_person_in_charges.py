from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT


class ProjectPersonInCharges(SQLModel, table=True):
    __tablename__ = "project_person_in_charges"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    project_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False))
    pic_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("employees.id"), nullable=False))
    is_lead: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
