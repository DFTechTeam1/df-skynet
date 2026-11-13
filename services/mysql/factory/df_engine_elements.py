from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_elements import DfEngineElements, ElementTypes
from utils import local_time


class DfEngineElementsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineElements
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    uid = LazyFunction(lambda: str(uuid4()))
    created_at = LazyFunction(local_time)
    updated_at = None
    types = ElementTypes.character
    name = Faker("word")
    description = Faker("sentence")
    task_id = None
    song_id = None
    project_id = None
    created_by = None
    updated_by = None
