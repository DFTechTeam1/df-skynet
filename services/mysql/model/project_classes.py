from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, SmallInteger, String
from sqlmodel import Column, Field, SQLModel, Relationship
from sqlalchemy.dialects.mysql import BIGINT


class ProjectClasses(SQLModel, table=True):
    __tablename__ = "project_classes" # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True))
    name: str = Field(sa_column=Column(String(255)))
    maximal_point: int = Field(sa_column=Column(SmallInteger))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    color: Optional[str] = Field(default=None, sa_column=Column(String(20), nullable=True))

    projects: list["Projects"] = Relationship(back_populates="project_classes") # type: ignore
