from datetime import date, datetime
from typing import Optional
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import BIGINT, CHAR, TINYINT

TRANSFER_STATUS_REQUESTED = 1
TRANSFER_STATUS_APPROVED = 2
TRANSFER_STATUS_REJECTED = 3
TRANSFER_STATUS_COMPLETED = 4


class TransferTeamMembers(SQLModel, table=True):
    __tablename__ = "transfer_team_members"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(sa_column=Column(CHAR(36), nullable=False))
    project_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("projects.id"), nullable=False))
    employee_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("employees.id"), nullable=True)
    )
    request_to: int = Field(sa_column=Column(Integer, ForeignKey("employees.id"), nullable=False))
    requested_by: int = Field(sa_column=Column(Integer, ForeignKey("employees.id"), nullable=False))
    reason: str = Field(sa_column=Column(String(255), nullable=False))
    reject_reason: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    device_action: Optional[str] = Field(default=None, sa_column=Column(String(10), nullable=True))
    status: int = Field(sa_column=Column(TINYINT, nullable=False))  # 1 requested, 2 approved, 3 reject, 4 completed
    is_entertainment: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    project_date: date = Field(sa_column=Column(Date, nullable=False))
    request_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    rejected_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    canceled_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
