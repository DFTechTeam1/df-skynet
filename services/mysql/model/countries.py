from sqlmodel import Column, Field, SQLModel
from sqlalchemy import String
from sqlmodel import Relationship
from sqlalchemy.dialects.mysql import BIGINT


class Countries(SQLModel, table=True):
    __tablename__ = "countries" # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    name: str = Field(sa_column=Column(String(255)))
    iso3: str = Field(sa_column=Column(String(255)))
    iso2: str = Field(sa_column=Column(String(255)))
    phone_code: str = Field(sa_column=Column(String(255)))
    currency: str = Field(sa_column=Column(String(255)))

    projects: list["Projects"] = Relationship(back_populates="countries") # type: ignore
    cities: list["Cities"] = Relationship(back_populates="countries") # type: ignore
    states: list["States"] = Relationship(back_populates="countries") # type: ignore