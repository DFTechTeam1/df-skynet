import json
from uuid import UUID
from typing import Optional, Any
from services.redis import get_json_sync, set_json_sync
from services.mysql.model import Projects
from log import logging
from services.mysql import query_sync
from utils.serializer import serialize
from error import DataNotFoundError
from services.dto import SyncedConnectionContext


def get_project(
    ctx: SyncedConnectionContext, project_uid: Optional[UUID] = None, project_id: Optional[int] = None
) -> dict[str, Any]:
    """Sync mirror of `services.dto.asynced.projects.get_project` for Celery
    tasks — same `CacheKeys.get_project` key, so a project cached by a web
    request and one cached by a task hit/invalidate consistently."""
    project_key = ctx.key.get_project(project_uid, project_id)
    project = get_json_sync(ctx.redis, project_key)
    if project:
        logging.info(f"project cache hit key={project_key}")
        return project

    filters = []
    if project_uid is not None:
        filters.append(Projects.uid == str(project_uid))
    if project_id is not None:
        filters.append(Projects.id == project_id)

    row = query_sync(ctx.db, Projects, filters=tuple(filters), fetch_one=True)
    if not row:
        logging.warning(f"project not found project_uid={project_uid} project_id={project_id}")
        raise DataNotFoundError(message="project_not_found")

    project = serialize(row)
    if project.get("led_detail"):
        project["led_detail"] = json.loads(project["led_detail"])
    set_json_sync(ctx.redis, project_key, project)
    logging.info(f"project cache set key={project_key}")
    return project
