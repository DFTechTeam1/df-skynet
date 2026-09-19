from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from services.mysql import get_db
from services.mysql.model import DfEngineUploadFileReferences, DfEngineGenerationReferences


async def attach_references(db: AsyncSession, generation_id: int, references: list[dict[str, Any]]):
    for ref in references:
        if ref["type"] == "upload":
            db.add(DfEngineUploadFileReferences(generation_id=generation_id, file_id=ref["id"]))
        if ref["type"] == "generated":
            db.add(DfEngineGenerationReferences(generation_id=generation_id, result_id=ref["id"]))
    await db.flush()
