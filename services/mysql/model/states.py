from sqlalchemy import String
from sqlmodel import Column, Field, SQLModel, Relationship, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from typing import Optional


class States(SQLModel, table=True):
    __tablename__ = "states"  # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    country_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("countries.id")))
    name: str = Field(sa_column=Column(String(255)))
    country_code: str = Field(sa_column=Column(String(255)))

    countries: Optional["Countries"] = Relationship(back_populates="states")  # type: ignore
    cities: list["Cities"] = Relationship(back_populates="states")  # type: ignore
    projects: list["Projects"] = Relationship(back_populates="states")  # type: ignore
