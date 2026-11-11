from typing import Optional
from sqlmodel import Column, Field, Relationship, SQLModel
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT


class DfEnginePromptTemplateReferences(SQLModel, table=True):
    __tablename__ = "df_engine_prompt_template_references"  # type: ignore
    __table_args__ = (
        UniqueConstraint("main_template_id", "reference_id", name="idx_prompt_template_references_unique_pair"),
    )

    id: int = Field(default=None, sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    main_template_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("df_engine_prompt_templates.id", ondelete="CASCADE"), nullable=False
        )
    )
    reference_id: int = Field(
        sa_column=Column(
            BIGINT(unsigned=True), ForeignKey("df_engine_prompt_templates.id", ondelete="CASCADE"), nullable=False
        )
    )

    reference: Optional["DfEnginePromptTemplates"] = Relationship(  # type: ignore
        sa_relationship_kwargs={"foreign_keys": "[DfEnginePromptTemplateReferences.reference_id]"}
    )
