from typing import Iterable
from sqlalchemy.ext.asyncio import AsyncSession
from services.search.docs import UPLOADED_FILES
from services.tasks.search_sync import search_delete, search_upsert


async def dispatch_search_sync(
    db: AsyncSession,
    generations: Iterable[str] = (),
    uploads: Iterable[str] = (),
    deleted_uploads: Iterable[str] = (),
) -> None:
    """Queue the index updates for what this request changed. The session only commits when the request ends, but the
    worker reads through its own connection, so commit first (as the generate endpoints do before `image_generation`).
    Does nothing, not even a commit, when there is nothing to sync."""
    generations, uploads, deleted_uploads = sorted(set(generations)), sorted(set(uploads)), sorted(set(deleted_uploads))
    if not (generations or uploads or deleted_uploads):
        return
    await db.commit()
    for uid in generations:
        search_upsert.delay("generation", uid)  # type: ignore
    for uid in uploads:
        search_upsert.delay("upload", uid)  # type: ignore
    if deleted_uploads:
        search_delete.delay(UPLOADED_FILES, deleted_uploads)  # type: ignore
