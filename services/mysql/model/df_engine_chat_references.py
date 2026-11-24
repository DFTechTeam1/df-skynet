from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.mysql import BIGINT


class DfEngineChatReferences(SQLModel, table=True):
    """Links a chat message to an attachment."""

    __tablename__ = "df_engine_chat_references"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    chat_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_chat_assistants.id"), nullable=False)
    )
    attachment_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("df_engine_attachments.id", ondelete="CASCADE"), nullable=False
        )
    )

    attachment: Optional["DfEngineAttachments"] = Relationship()  # type: ignore
