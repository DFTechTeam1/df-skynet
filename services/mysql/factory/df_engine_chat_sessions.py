from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_chat_sessions import DfEngineChatSessions
from utils import local_time
from uuid import uuid4


class DfEngineChatSessionsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineChatSessions
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = LazyFunction(local_time)
    uid = LazyFunction(lambda: str(uuid4()))
    topic = LazyFunction(lambda: f"Topic {uuid4().hex[:8]}")
    menu_id = None
    project_id = None
    created_by = None
