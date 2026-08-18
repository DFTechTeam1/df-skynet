from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import DateTime, String
from sqlalchemy.dialects.mysql import BIGINT


class Permissions(SQLModel, table=True):
    __tablename__ = "permissions"  # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True))
    name: str = Field(sa_column=Column(String(255)))
    guard_name: str = Field(sa_column=Column(String(255)))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    group: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    model_has_permissions: list["ModelHasPermissions"] = Relationship(back_populates="permissions")  # type: ignore
    role_has_permissions: list["RoleHasPermissions"] = Relationship(back_populates="permissions")  # type: ignore
