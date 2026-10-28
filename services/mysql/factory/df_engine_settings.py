from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction, Sequence
from factory.faker import Faker
from services.mysql.model.df_engine_settings import DfEngineSettings
from utils import local_time


class DfEngineSettingsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineSettings
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    key = Sequence(lambda n: f"setting_key_{n}")
    value = Faker("text")
    created_at = LazyFunction(local_time)
    updated_at = None
    code = None
