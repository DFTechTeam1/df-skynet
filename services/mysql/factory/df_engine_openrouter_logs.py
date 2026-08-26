from uuid import uuid4

from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_openrouter_logs import DfEngineOpenrouterLogs
from utils import local_time


class DfEngineOpenrouterLogsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineOpenrouterLogs
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    uid = LazyFunction(lambda: str(uuid4()))
    name = None
    method = "GET"
    endpoint = Faker("uri_path")
    request_headers = None
    request_payload = None
    response_status_code = None
    response_headers = None
    response_body = None
    error_message = None
    duration_ms = None
