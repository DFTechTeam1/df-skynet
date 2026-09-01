from uuid import uuid4
from secrets import token_hex
from factory.declarations import LazyFunction, Sequence
from factory.faker import Faker
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from utils import local_time
from apps.secret import DB_SYNC_URL
from services.mysql import make_sync_session
from factory.alchemy import SQLAlchemyModelFactory


class DfEngineApiKeysFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineApiKeys
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = None
    expires_at = None
    limit = None
    limit_reset = None
    uid = LazyFunction(lambda: str(uuid4()))
    key = LazyFunction(lambda: f"sk-or-v1-{token_hex(32)}")
    hash = LazyFunction(lambda: token_hex(32))
    name = Sequence(lambda n: f"API Key {n}")
    description = Faker("sentence")
    employee_id = None
    employee_name = None
    is_main = False
    created_by = None
    updated_by = None
