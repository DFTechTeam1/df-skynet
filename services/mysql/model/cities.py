from sqlmodel import Column, Field, SQLModel, Relationship, ForeignKey
from sqlalchemy import String
from sqlalchemy.dialects.mysql import BIGINT
from typing import Optional


class Cities(SQLModel, table=True):
    __tablename__ = "cities"  # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    country_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("countries.id")))
    state_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("states.id")))
    name: str = Field(sa_column=Column(String(255)))
    country_code: str = Field(sa_column=Column(String(255)))

    countries: Optional["Countries"] = Relationship(back_populates="cities")  # type: ignore
    states: Optional["States"] = Relationship(back_populates="cities")  # type: ignore
    projects: list["Projects"] = Relationship(back_populates="cities")  # type: ignore
