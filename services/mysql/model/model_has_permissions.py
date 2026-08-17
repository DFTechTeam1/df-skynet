from typing import Optional
from sqlalchemy import ForeignKey, String
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy.dialects.mysql import BIGINT


class ModelHasPermissions(SQLModel, table=True):
    __tablename__ = "model_has_permissions" #type: ignore
    
    permission_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("permissions.id"), primary_key=True))
    model_type: str = Field(sa_column=Column(String(255), primary_key=True))
    model_id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True))

    permissions: Optional["Permissions"] = Relationship(back_populates="model_has_permissions") #type: ignore
