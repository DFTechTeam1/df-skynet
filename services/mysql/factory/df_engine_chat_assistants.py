from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from services.mysql.model.df_engine_chat_assistants import DfEngineChatAssistants


class DfEngineChatAssistantsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineChatAssistants
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    uid = None
    placeholder = None
    created_by = None
