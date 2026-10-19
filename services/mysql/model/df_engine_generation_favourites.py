from datetime import datetime
from sqlmodel import Column, Field, SQLModel
from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT
from utils import local_time


class DfEngineGenerationFavourites(SQLModel, table=True):
    """One row per (user, generation result): the result is favourited by that user."""

    __tablename__ = "df_engine_generation_favourites"  # type: ignore
    __table_args__ = (UniqueConstraint("user_id", "result_id", name="uq_generation_favourites_user_result"),)

    id: int = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    favourited_at: datetime = Field(default_factory=local_time, sa_column=Column(DateTime, nullable=False))
    user_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=False))
    result_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True),
            ForeignKey("df_engine_generation_results.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
