from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import CHAR, DECIMAL, Boolean, DateTime, ForeignKey, Integer, String, Text, false
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineChatAssistants(SQLModel, table=True):
    """One chat message inside a `DfEngineChatSessions` row."""

    __tablename__ = "df_engine_chat_assistants"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    session_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_chat_sessions.id"), nullable=False)
    )
    content: str = Field(sa_column=Column(Text(length=4294967295), nullable=False))
    role: str = Field(sa_column=Column(String(255), nullable=False))  # system, assistant, user
    model: str = Field(sa_column=Column(String(255), nullable=False))
    status_code: int = Field(default=200, sa_column=Column(Integer, nullable=False, server_default="200"))
    total_tokens: int = Field(default=0, sa_column=Column(BIGINT(unsigned=True), nullable=False, server_default="0"))
    cached_tokens: int = Field(default=0, sa_column=Column(BIGINT(unsigned=True), nullable=False, server_default="0"))
    cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(10, 2), nullable=False, server_default="0"))
    exchange_rate: Decimal = Field(
        default=Decimal("0"), sa_column=Column(DECIMAL(20, 8), nullable=False, server_default="0")
    )
    has_generation_prompt: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=false())
    )
    sender: str = Field(sa_column=Column(String(255), nullable=False))  # <username> or openrouter
