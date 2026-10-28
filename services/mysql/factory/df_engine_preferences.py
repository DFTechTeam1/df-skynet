from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_preferences import DfEnginePreferences
from utils import local_time


class DfEnginePreferencesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEnginePreferences
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = None
    theme = "dark"
    accent = "teal"
    language = "english"
    default_aspect_ratio = "16:9"
    default_size = "4K"
    confirm_before_spending = "over_0.5"
