from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import CHAR, DateTime, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineActionMappings(SQLModel, table=True):
    __tablename__ = "df_engine_action_mappings" # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    created_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    uid: str = Field(sa_column=Column(CHAR(36), nullable=False, unique=True))
    action_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_actions.id"), nullable=False))
    template_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_prompt_templates.id"), nullable=False))

    df_engine_actions: Optional["DfEngineActions"] = Relationship(back_populates="df_engine_action_mappings") # type: ignore
    df_engine_prompt_templates: Optional["DfEnginePromptTemplates"] = Relationship(back_populates="df_engine_action_mappings") # type: ignore
