from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import BigInteger, CHAR, Integer, DateTime, String
from sqlalchemy.dialects.mysql import BIGINT


class PositionBackups(SQLModel, table=True):
    __tablename__ = "position_backups"  # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True))
    uid: str = Field(sa_column=Column(CHAR(36)))
    name: str = Field(sa_column=Column(String(255)))
    division_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    created_by: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    updated_by: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )

    employees: list["Employees"] = Relationship(back_populates="position_backups")  # type: ignore
