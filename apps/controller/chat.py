import traceback
from uuid import UUID
from fastapi import Form, Path, Query, Request, status
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from error import BaseError, ServiceError
from log import logging
from schemas.payload.chat import RenameChatPayload
from schemas.response import Response
from services.chat_assistant import (
    continue_chat,
    get_chat_detail,
    list_chats,
    rename_chat,
    start_chat,
    toggle_archive,
)
from services.dto import ConnectionContext
from services.redis import CacheKeys

cache_key = CacheKeys()


class ChatController(CoreDependencies):
    @controller.get(
        "/chats",
        summary="List my chat assistants.",
        description=(
            "Lists the chats the current user started. `archived=false` (default) returns active chats, "
            "`archived=true` returns archived ones. Newest activity first, paginated. Only active chats can continue "
            "the conversation."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Chat"],
        response_model=Response,
    )
    async def chat_list(
        self,
        archived: bool = Query(False, description="true = archived chats, false = active chats."),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=20, ge=1, le=100, description="Number of chats to return per page."),
    ) -> Response:
        response = Response()
        try:
            ctx = ConnectionContext(self.db, self.redis, cache_key)
            response.data = await list_chats(ctx, int(self.user["user_id"]), archived, page, itemsPerPage)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/chat/new",
        summary="Start a chat assistant.",
        description=(
            "Starts a new chat with the first `prompt` and optional images (PNG/JPEG/WebP) sent as multipart fields `images[0]`, `images[1]`, ... `images[n]`. The prompt is validated before the assistant answers. Returns the conversation, same as the detail endpoint."
        ),
        status_code=status.HTTP_201_CREATED,
        tags=["Chat"],
        response_model=Response,
    )
    async def chat_create(
        self,
        request: Request,
        prompt: str = Form(..., min_length=1, description="First message."),
    ) -> Response:
        response = Response()
        try:
            ctx = ConnectionContext(self.db, self.redis, cache_key)
            response.data = await start_chat(ctx, self.user, prompt, request)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.get(
        "/chat/{chat_uid}",
        summary="Get a chat assistant conversation.",
        description="Returns the whole conversation from the first message to the latest, with attached image URLs.",
        status_code=status.HTTP_200_OK,
        tags=["Chat"],
        response_model=Response,
    )
    async def chat_with_chat_uid_to_fetch_detail(self, chat_uid: UUID = Path(..., description="Chat UID.")) -> Response:
        response = Response()
        try:
            ctx = ConnectionContext(self.db, self.redis, cache_key)
            response.data = await get_chat_detail(ctx, chat_uid, int(self.user["user_id"]))
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/chat/{chat_uid}",
        summary="Continue a chat assistant conversation.",
        description=(
            "Adds a message (and optional images as `images[0]`, `images[1]`, ... `images[n]`) to an active chat. The whole conversation so far is sent to the "
            "model for context. Returns the whole conversation including the new turn, same as the detail endpoint. Only the creator can post, archived chats must be unarchived first, and a chat accepts at most 20 messages."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Chat"],
        response_model=Response,
    )
    async def chat_with_chat_uid_to_continue_chat(
        self,
        request: Request,
        chat_uid: UUID = Path(..., description="Chat UID."),
        prompt: str = Form(..., min_length=1, description="Next message."),
    ) -> Response:
        response = Response()
        try:
            ctx = ConnectionContext(self.db, self.redis, cache_key)
            response.data = await continue_chat(ctx, chat_uid, self.user, prompt, request)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/chat/{chat_uid}",
        summary="Rename a chat assistant.",
        description="Changes the chat's name (`placeholder`, at least 1 character). Creator only. Returns no data.",
        status_code=status.HTTP_200_OK,
        tags=["Chat"],
        response_model=Response,
    )
    async def chat_with_chat_uid_to_rename_placeholder(
        self, payload: RenameChatPayload, chat_uid: UUID = Path(..., description="Chat UID.")
    ) -> Response:
        response = Response()
        try:
            ctx = ConnectionContext(self.db, self.redis, cache_key)
            await rename_chat(ctx, chat_uid, int(self.user["user_id"]), payload.placeholder)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.delete(
        "/chat/{chat_uid}",
        summary="Archive or unarchive a chat assistant.",
        description=(
            "Toggles the archive state: archives an active chat, unarchives an archived one, so calling it "
            "twice puts the chat back. Creator only. Returns no data."
        ),
        status_code=status.HTTP_200_OK,
        tags=["Chat"],
        response_model=Response,
    )
    async def chat_toggle_archive(self, chat_uid: UUID = Path(..., description="Chat UID.")) -> Response:
        response = Response()
        try:
            ctx = ConnectionContext(self.db, self.redis, cache_key)
            await toggle_archive(ctx, chat_uid, int(self.user["user_id"]))
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
