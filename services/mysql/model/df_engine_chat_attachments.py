from typing import Any, Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import Index, String, and_
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import foreign
from services.mysql.model.df_engine_generation_results import DfEngineGenerationResults
from services.mysql.model.df_engine_upload_files import DfEngineUploadFiles


class DfEngineChatAttachments(SQLModel, table=True):
    """Polymorphic: `sourceable_type` is `DfEngineUploadFiles` or `DfEngineGenerationResults` (no DB FK)."""

    __tablename__ = "df_engine_chat_attachments"  # type: ignore
    __table_args__ = (Index("idx_chat_attachments_sourceable", "sourceable_type", "sourceable_id"),)

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    sourceable_id: int = Field(sa_column=Column(BIGINT(unsigned=True), nullable=False))
    sourceable_type: str = Field(sa_column=Column(String(255), nullable=False))

    upload_file: Optional["DfEngineUploadFiles"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineChatAttachments.sourceable_id) == DfEngineUploadFiles.id,  # type: ignore
                DfEngineChatAttachments.sourceable_type == DfEngineUploadFiles.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )
    generation_result: Optional["DfEngineGenerationResults"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(  # type: ignore
                foreign(DfEngineChatAttachments.sourceable_id) == DfEngineGenerationResults.id,  # type: ignore
                DfEngineChatAttachments.sourceable_type == DfEngineGenerationResults.__name__,  # type: ignore
            ),
            "viewonly": True,
            "uselist": False,
        }
    )

    @property
    def sourceable(self) -> Optional[Any]:
        """The resolved `upload_file`/`generation_result`, whichever `sourceable_type` points at.
        Requires that relationship to already be loaded (e.g. via `selectinload`)."""
        return self.upload_file if self.sourceable_type == DfEngineUploadFiles.__name__ else self.generation_result
