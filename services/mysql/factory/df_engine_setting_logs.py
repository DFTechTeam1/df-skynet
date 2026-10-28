from uuid import uuid4

from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_setting_logs import DfEngineSettingLogs
from utils import local_time


class DfEngineSettingLogsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineSettingLogs
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    uid = LazyFunction(lambda: str(uuid4()))
    created_by = None
    user_email = Faker("email")
    user_name = Faker("name")
    previous_data = None
    incoming_data = LazyFunction(dict)
    ip_address = Faker("ipv4")
    user_agent = Faker("user_agent")
