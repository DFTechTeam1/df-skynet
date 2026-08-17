from typing import Optional
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy.dialects.mysql import BIGINT


class ModelHasRoles(SQLModel, table=True):
    __tablename__ = "model_has_roles"  # type: ignore

    role_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("roles.id"), primary_key=True
        )
    )
    model_type: str = Field(sa_column=Column(String(255), primary_key=True))
    model_id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True))

    roles: Optional["Roles"] = Relationship(back_populates="model_has_roles")  # type: ignore
