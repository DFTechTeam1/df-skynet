from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, CHAR, DateTime, SmallInteger, String
from sqlmodel import Column, Field, SQLModel, Relationship
from sqlalchemy.dialects.mysql import BIGINT


class Users(SQLModel, table=True):
    __tablename__ = "users"  # type: ignore

    id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    )
    uid: str = Field(sa_column=Column(CHAR(36)))
    email: str = Field(sa_column=Column(String(255)))
    email_verified_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    password: str = Field(sa_column=Column(String(255)))
    image: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    last_login_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    remember_token: Optional[str] = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    created_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    is_external_user: int = Field(default=0, sa_column=Column(SmallInteger))
    username: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    employee_id: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    is_employee: Optional[int] = Field(
        default=None, sa_column=Column(SmallInteger, nullable=True)
    )
    is_project_manager: Optional[int] = Field(
        default=None, sa_column=Column(SmallInteger, nullable=True)
    )
    is_director: Optional[int] = Field(
        default=None, sa_column=Column(SmallInteger, nullable=True)
    )
    reset_password_token_exp: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    reset_password_token_claim: Optional[int] = Field(
        default=None, sa_column=Column(SmallInteger, nullable=True)
    )
    deleted_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )

    employees: Optional["Employees"] = Relationship(
        back_populates="users", sa_relationship_kwargs={"uselist": False}
    )  # type: ignore
