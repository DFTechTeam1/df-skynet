from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_generation_references import DfEngineGenerationReferences
from utils import local_time


class DfEngineGenerationReferencesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineGenerationReferences
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    generation_id = None
    result_id = None
