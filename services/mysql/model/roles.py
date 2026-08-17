from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, SmallInteger, String
from sqlalchemy.dialects.mysql import BIGINT


class Roles(SQLModel, table=True):
    __tablename__ = "roles" # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    name: str = Field(sa_column=Column(String(255)))
    guard_name: str = Field(sa_column=Column(String(255)))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    is_permanent: int = Field(default=0, sa_column=Column(SmallInteger))

    model_has_roles: list["ModelHasRoles"] = Relationship(back_populates="roles") # type: ignore
    role_has_permissions: list["RoleHasPermissions"] = Relationship(back_populates="roles") # type: ignore