from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import Boolean, CHAR, DateTime, DECIMAL, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineApiKeys(SQLModel, table=True):
    __tablename__ = "df_engine_api_keys"  # type: ignore

    id: int = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    )
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    expired_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    limit_usage: Optional[float] = Field(default=None, sa_column=Column(DECIMAL(10, 2), nullable=True))
    limit_reset: Optional[str] = Field(default=None, sa_column=Column(String(20), nullable=True))
    uid: str = Field(sa_column=Column(CHAR(36), nullable=False, unique=True))
    key: str = Field(sa_column=Column(Text, nullable=False))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    employee_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("employees.id"), nullable=False))
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    created_by: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False))
    updated_by: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True),
    )
    deleted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))

    employees: Optional["Employees"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineApiKeys.employee_id]"}
    )
    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineApiKeys.created_by]"}
    )
    updated_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEngineApiKeys.updated_by]"}
    )
