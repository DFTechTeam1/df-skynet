from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_generation_results import DfEngineGenerationResults
from utils import local_time


class DfEngineGenerationResultsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineGenerationResults
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    uid = LazyFunction(lambda: str(uuid4()))
    created_at = LazyFunction(local_time)
    updated_at = None
    archieved_at = None
    generation_id = None
    parent_id = None
    md5 = LazyFunction(lambda: uuid4().hex)
    name = Faker("file_name", category="image")
    path = Faker("file_path", depth=2, category="image")
    size = Faker("random_int", min=1024, max=10_485_760)
    is_main = True
    is_favourite = False
    created_by = None
    updated_by = None
