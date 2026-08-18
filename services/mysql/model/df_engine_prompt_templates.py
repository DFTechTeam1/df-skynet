from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import Boolean, CHAR, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEnginePromptTemplates(SQLModel, table=True):
    __tablename__ = "df_engine_prompt_templates"  # type: ignore

    id: int = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    )
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    uid: str = Field(sa_column=Column(CHAR(36), nullable=False, unique=True))
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    name: str = Field(sa_column=Column(String(255), nullable=False, unique=True))
    prompt: str = Field(sa_column=Column(Text, nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_by: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False))
    updated_by: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True),
    )

    created_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEnginePromptTemplates.created_by]"}
    )
    updated_by_user: Optional["Users"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEnginePromptTemplates.updated_by]"}
    )
    df_engine_action_mappings: list["DfEngineActionMappings"] = Relationship(  # type: ignore
        back_populates="df_engine_prompt_templates"
    )
