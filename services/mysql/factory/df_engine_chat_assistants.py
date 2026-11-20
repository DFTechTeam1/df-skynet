from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_chat_assistants import DfEngineChatAssistants
from utils import local_time
from uuid import uuid4


class DfEngineChatAssistantsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineChatAssistants
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    uid = LazyFunction(lambda: str(uuid4()))
    created_at = LazyFunction(local_time)
    session_id = None
    content = "hello"
    role = "user"
    model_id = None
    status = "success"
    status_code = 200
    total_tokens = 0
    cached_tokens = 0
    cost = 0
    exchange_rate = 0
    has_generation_prompt = False
    sender = "tester"
    apikeyable_id = None
    apikeyable_type = None
