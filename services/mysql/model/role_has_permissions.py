from typing import Optional
from sqlalchemy import ForeignKey
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy.dialects.mysql import BIGINT


class RoleHasPermissions(SQLModel, table=True):
    __tablename__ = "role_has_permissions"  # type: ignore

    permission_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("permissions.id"), primary_key=True
        )
    )
    role_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("roles.id"), primary_key=True
        )
    )

    roles: Optional["Roles"] = Relationship(back_populates="role_has_permissions")  # type: ignore
    permissions: Optional["Permissions"] = Relationship(
        back_populates="role_has_permissions"
    )  # type: ignore
