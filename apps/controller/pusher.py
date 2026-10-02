import re
from fastapi import status
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from schemas.payload.pusher import PusherChannelAuthPayload
from schemas.response import Response
from services.pusher import get_pusher
from error import AuthorizationError

CHANNEL_RE = re.compile(r"^private-user-generation-project-\d+-task-\d+-user-(\d+)$")


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
        if not match or match.group(1) != str(int(self.user["user_id"])):
            raise AuthorizationError(message="channel_access_denied")
        response.data = get_pusher().authenticate(schema.channel_name, schema.socket_id)
        return response
