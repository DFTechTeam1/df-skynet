from typing import Optional
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT


class DfEngineChatAssistantImageReferences(SQLModel, table=True):
    __tablename__ = "df_engine_chat_assistant_image_references"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    chat_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("df_engine_chat_assistants.id", ondelete="CASCADE"), nullable=False
        )
    )
    generation_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("df_engine_generations.id", ondelete="CASCADE"), nullable=True
        ),
    )
    path: str = Field(sa_column=Column(String(512), nullable=False))
