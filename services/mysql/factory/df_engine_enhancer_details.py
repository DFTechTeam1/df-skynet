from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.faker import Faker
from services.mysql.model.df_engine_enhancer_details import DfEngineEnhancerDetails


class DfEngineEnhancerDetailsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineEnhancerDetails
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    generation_id = None
    raw = Faker("sentence")
    enhanced = Faker("paragraph")
