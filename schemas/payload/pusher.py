from pydantic import BaseModel, Field


class PusherChannelAuthPayload(BaseModel):
    channel_name: str
    socket_id: str = Field(pattern=r"^\d+\.\d+$", description="Pusher connection socket ID, e.g. 123456.654321.")
