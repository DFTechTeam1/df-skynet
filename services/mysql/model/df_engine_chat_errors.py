from sqlmodel import Column, Field, SQLModel
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.mysql import BIGINT


class DfEngineChatErrors(SQLModel, table=True):
    """An error raised while answering a `DfEngineChatAssistants` message. One message can have many."""

    __tablename__ = "df_engine_chat_errors"  # type: ignore

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    chat_id: int = Field(
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("df_engine_chat_assistants.id"), nullable=False)
    )
    message: str = Field(sa_column=Column(Text, nullable=False))
