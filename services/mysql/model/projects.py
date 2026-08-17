from datetime import date, datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy.dialects.mysql import BIGINT
from enum import StrEnum, auto
from sqlalchemy import (
    ForeignKey,
    String,
    Text,
    Date,
    DateTime,
    Double,
    Integer,
    SmallInteger,
    Enum,
    CHAR,
)

class ProjectEventTypes(StrEnum):
    wedding = auto()
    engagement = auto()
    event = auto()
    birthday = auto()
    concert = auto()
    corporate = auto()
    exhibition = auto()


class Projects(SQLModel, table=True):
    __tablename__ = "projects" # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    identifier_id: Optional[str] = Field(default=None, sa_column=Column(String(20)))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    client_portal: str = Field(sa_column=Column(String(255), nullable=False))
    project_date: date = Field(sa_column=Column(Date, nullable=False))
    event_type: Optional[ProjectEventTypes] = Field(default=None, sa_column=Column(Enum(ProjectEventTypes), nullable=True))
    venue: str = Field(sa_column=Column(String(255), nullable=False))
    marketing_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    collaboration: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: Optional[int] = Field(default=None, sa_column=Column(SmallInteger, nullable=True))
    created_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    updated_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    led_area: float = Field(default=0, sa_column=Column(Double, nullable=False))
    led_detail: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    uid: str = Field(sa_column=Column(CHAR(36), nullable=False))
    showreels: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    country_id: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("countries.id")))
    state_id: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("states.id")))
    city_id: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("cities.id")))
    city_name: Optional[str] = Field(default=None, sa_column=Column(String(22), nullable=True))
    classification: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    showreels_status: Optional[int] = Field(default=None, sa_column=Column(SmallInteger, nullable=True))
    longitude: Optional[str] = Field(default=None, sa_column=Column(String(150), nullable=True))
    latitude: Optional[str] = Field(default=None, sa_column=Column(String(150), nullable=True))
    feedback: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    project_class_id: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), ForeignKey("project_classes.id")))

    countries: Optional["Countries"] = Relationship(back_populates="projects") # type: ignore
    states: Optional["States"] = Relationship(back_populates="projects") # type: ignore
    cities: Optional["Cities"] = Relationship(back_populates="projects") # type: ignore
    project_classes: Optional["ProjectClasses"] = Relationship(back_populates="projects") # type: ignore