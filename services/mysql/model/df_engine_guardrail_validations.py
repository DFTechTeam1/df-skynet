from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import CHAR, DECIMAL, JSON, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineGuardrailValidations(SQLModel, table=True):
    __tablename__ = "df_engine_guardrail_validations"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    menu_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_menus.id"), nullable=False))
    feature_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_features.id"), nullable=False)
    )
    payload: Any = Field(sa_column=Column(JSON, nullable=False))
    response: Any = Field(sa_column=Column(JSON, nullable=False))
    status_code: int = Field(default=200, sa_column=Column(Integer, nullable=False, server_default="200"))
    total_tokens: int = Field(default=0, sa_column=Column(BIGINT(unsigned=True), nullable=False, server_default="0"))
    cached_tokens: int = Field(default=0, sa_column=Column(BIGINT(unsigned=True), nullable=False, server_default="0"))
    cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(10, 2), nullable=False, server_default="0"))
    exchange_rate: Decimal = Field(
        default=Decimal("0"), sa_column=Column(DECIMAL(20, 8), nullable=False, server_default="0")
    )
    created_by: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False))
