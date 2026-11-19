from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from services.mysql.model.df_engine_chat_references import DfEngineChatReferences


class DfEngineChatReferencesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineChatReferences
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    chat_id = None
    attachment_id = None
