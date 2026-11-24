from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DECIMAL, JSON, DateTime, ForeignKey, Integer, String, Text, and_
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import foreign
from services.mysql.model.df_engine_api_key_snapshots import DfEngineApiKeySnapshots
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from utils import local_time


class DfEngineGuardrailValidations(SQLModel, table=True):
    __tablename__ = "df_engine_guardrail_validations"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(CHAR(36), nullable=False, unique=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    sourceable_id: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), nullable=True))
    sourceable_type: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    apikeyable_id: Optional[int] = Field(default=None, sa_column=Column(BIGINT(unsigned=True), nullable=True))
    apikeyable_type: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    model_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_model_options.id"), nullable=True),
    )
    message: str = Field(sa_column=Column(Text, nullable=False))
    payload: Any = Field(sa_column=Column(JSON, nullable=False))
    response: Any = Field(sa_column=Column(JSON, nullable=False))
    status_code: int = Field(default=200, sa_column=Column(Integer, nullable=False, server_default="200"))
    total_tokens: int = Field(default=0, sa_column=Column(BIGINT(unsigned=True), nullable=False, server_default="0"))
    cached_tokens: int = Field(default=0, sa_column=Column(BIGINT(unsigned=True), nullable=False, server_default="0"))
    cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(12, 6), nullable=False, server_default="0"))
    exchange_rate: Decimal = Field(
        default=Decimal("0"), sa_column=Column(DECIMAL(20, 8), nullable=False, server_default="0")
    )
    created_by: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False))

    model_option: Optional["DfEngineModelOptions"] = Relationship(back_populates="guardrail_validations")  # type: ignore
    api_key: Optional["DfEngineApiKeys"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineGuardrailValidations.apikeyable_id) == DfEngineApiKeys.id,  # type: ignore
                DfEngineGuardrailValidations.apikeyable_type == DfEngineApiKeys.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )
    api_key_snapshot: Optional["DfEngineApiKeySnapshots"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineGuardrailValidations.apikeyable_id) == DfEngineApiKeySnapshots.id,  # type: ignore
                DfEngineGuardrailValidations.apikeyable_type == DfEngineApiKeySnapshots.__name__,  # type: ignore
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
