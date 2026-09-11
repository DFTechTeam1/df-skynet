from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_motion_details import DfEngineMotionDetails, Motions


class DfEngineMotionDetailsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineMotionDetails
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    generation_id = None
    updated_at = None
    archieved_at = None
    shot_id = None
    motion = Motions.static
    parameter = LazyFunction(dict)
