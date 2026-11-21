from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DECIMAL, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, and_, false
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import foreign
from services.mysql.model.df_engine_api_key_snapshots import DfEngineApiKeySnapshots
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from utils import local_time
from enums.base import QueueStatuses


class DfEngineChatAssistants(SQLModel, table=True):
    __tablename__ = "df_engine_chat_assistants"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    session_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_chat_sessions.id"), nullable=False)
    )
    content: str = Field(sa_column=Column(Text(length=4294967295), nullable=False))
    role: str = Field(sa_column=Column(String(255), nullable=False))  # system, assistant, user
    model_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_model_options.id"), nullable=True),
    )
    status: QueueStatuses = Field(
        default=QueueStatuses.success,
        sa_column=Column(
            Enum(QueueStatuses, name="chat_assistant_statuses"),
            nullable=False,
            server_default=QueueStatuses.success.value,
        ),
    )
    status_code: Optional[int] = Field(default=200, sa_column=Column(Integer, nullable=True))
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
    apikeyable_id: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), nullable=True))
    apikeyable_type: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))

    chat_references: list["DfEngineChatReferences"] = Relationship()  # type: ignore
    model_option: Optional["DfEngineModelOptions"] = Relationship(back_populates="chat_assistants")  # type: ignore
    api_key: Optional["DfEngineApiKeys"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineChatAssistants.apikeyable_id) == DfEngineApiKeys.id,  # type: ignore
                DfEngineChatAssistants.apikeyable_type == DfEngineApiKeys.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )
    api_key_snapshot: Optional["DfEngineApiKeySnapshots"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineChatAssistants.apikeyable_id) == DfEngineApiKeySnapshots.id,  # type: ignore
                DfEngineChatAssistants.apikeyable_type == DfEngineApiKeySnapshots.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )

    @property
    def apikeyable(self) -> Optional[Any]:
        """The resolved `api_key`/`api_key_snapshot`, whichever `apikeyable_type` points at.
        Requires that relationship to already be loaded (e.g. via `selectinload`)."""
        return self.api_key if self.apikeyable_type == DfEngineApiKeys.__name__ else self.api_key_snapshot
