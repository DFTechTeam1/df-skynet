from typing import Any, Optional
from sqlalchemy import case, distinct, func
from services.mysql.model import DfEngineAttachments, DfEngineChatAssistants, DfEngineChatReferences
from services.repository.base import BaseRepository


class ChatAssistantRepository(BaseRepository):
    async def get_chat_assistant(
        self,
        filters: Optional[tuple[Any, ...]] = None,
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
        fetch_one: bool = True,
        limit: Optional[int] = None,
        group_by: Optional[tuple[Any, ...]] = None,
        having: Optional[tuple[Any, ...]] = None,
        order_by: Optional[tuple[Any, ...]] = None,
        offset: Optional[int] = None,
    ) -> Any:
        return await self._get(
            DfEngineChatAssistants,
            (DfEngineChatAssistants.cost,),
            "chat_assistant_not_found",
            filters,
            columns,
            options,
            joins,
            raise_if_null,
            context,
            fetch_one,
            limit,
            group_by,
            having,
            order_by,
            offset,
        )

    async def get_session_stats(self, session_ids: list[int]) -> dict[int, dict[str, int]]:
        if not session_ids:
            return {}
        message_id = case((DfEngineChatAssistants.role.in_(["user", "assistant"]), DfEngineChatAssistants.id))  # type: ignore
        file_key = func.concat(DfEngineAttachments.sourceable_type, ":", DfEngineAttachments.sourceable_id)
        rows = await self.get_chat_assistant(
            columns=(
                DfEngineChatAssistants.session_id,
                func.count(distinct(message_id)).label("total_messages"),
                func.count(distinct(file_key)).label("total_unique_attachments"),
            ),
            joins=(
                (DfEngineChatReferences, DfEngineChatReferences.chat_id == DfEngineChatAssistants.id, True),
                (DfEngineAttachments, DfEngineAttachments.id == DfEngineChatReferences.attachment_id, True),
            ),
            filters=(DfEngineChatAssistants.session_id.in_(session_ids),),  # type: ignore
            group_by=(DfEngineChatAssistants.session_id,),
            fetch_one=False,
            raise_if_null=False,
        )
        return {row["session_id"]: row for row in rows}
