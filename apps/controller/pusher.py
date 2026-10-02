import re
from uuid import UUID
from fastapi import status
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from schemas.payload.pusher import PusherChannelAuthPayload
from schemas.response import Response
from services.dto import ConnectionContext
from services.dto.asynced.projects import get_project_task
from services.mysql import query
from services.mysql.model import Users
from services.pusher import get_pusher
from services.redis import CacheKeys
from error import AuthorizationError, DataNotFoundError

_UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
CHANNEL_RE = re.compile(rf"^private-user-generation-project-({_UUID_RE})-task-({_UUID_RE})-user-({_UUID_RE})$")
cache_key = CacheKeys()


class PusherController(CoreDependencies):
    @controller.post(
        "/pusher/auth",
        summary="Authorize a Pusher private channel subscription.",
        status_code=status.HTTP_200_OK,
        tags=["Pusher"],
        response_model=Response,
    )
    async def pusher_to_authorize_channel_subscription(self, schema: PusherChannelAuthPayload) -> Response:
        response = Response()
        match = CHANNEL_RE.match(schema.channel_name)
        if not match:
            raise AuthorizationError(message="channel_access_denied")
        project_uid, task_uid, user_uid = match.groups()
        user_row = await query(
            db=self.db, table=Users, filters=(Users.id == int(self.user["user_id"]),), fetch_one=True
        )
        if not user_row or user_uid != str(user_row.uid):
            raise AuthorizationError(message="channel_access_denied")
        ctx = ConnectionContext(self.db, self.redis, cache_key)
        task = await get_project_task(ctx, task_uid=UUID(task_uid))
        if task["project"]["uid"] != project_uid:
            raise DataNotFoundError(message="project_task_not_found")
        response.data = get_pusher().authenticate(schema.channel_name, schema.socket_id)
        return response
