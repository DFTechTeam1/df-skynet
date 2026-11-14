from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from services.mysql.model.df_engine_element_generations import DfEngineElementGenerations


class DfEngineElementGenerationsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineElementGenerations
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    element_id = None
    generation_id = None
