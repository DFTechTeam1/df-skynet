from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_storyboard_details import DfEngineStoryboardDetails


class DfEngineStoryboardDetailsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineStoryboardDetails
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    generation_id = None
    name = LazyFunction(lambda: f"Storyboard {uuid4().hex[:8]}")
    description = Faker("sentence")
