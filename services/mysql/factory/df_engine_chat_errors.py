from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from services.mysql.model.df_engine_chat_errors import DfEngineChatErrors


class DfEngineChatErrorsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineChatErrors
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    chat_id = None
    message = "error"
