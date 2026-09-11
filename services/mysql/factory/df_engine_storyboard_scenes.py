from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_storyboard_scenes import DfEngineStoryboardScenes
from utils import local_time


class DfEngineStoryboardScenesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineStoryboardScenes
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = None
    story_id = None
