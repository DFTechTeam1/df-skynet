from sqlalchemy.orm import load_only
from uuid import UUID
from typing import Optional, Any
from services.mysql.model import Projects
from log import logging
from services.mysql import query_sync
from utils.serializer import serialize
from error import DataNotFoundError
from services.dto import SyncedConnectionContext


def get_project(
    ctx: SyncedConnectionContext, project_uid: Optional[UUID] = None, project_id: Optional[int] = None
) -> dict[str, Any]:
    """Sync mirror of `services.dto.asynced.projects.get_project` for Celery tasks. Uncached."""
    filters = []
    if project_uid is not None:
        filters.append(Projects.uid == str(project_uid))
    if project_id is not None:
        filters.append(Projects.id == project_id)

    row = query_sync(
        ctx.db,
        Projects,
        options=(load_only(Projects.id, Projects.uid, Projects.name),),
        filters=tuple(filters),
        fetch_one=True,
    )
    if not row:
        logging.warning(f"project not found project_uid={project_uid} project_id={project_id}")
        raise DataNotFoundError(message="project_not_found")

    return serialize(row)
