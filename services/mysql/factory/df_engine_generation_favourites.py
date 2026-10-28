from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_generation_favourites import DfEngineGenerationFavourites
from utils import local_time


class DfEngineGenerationFavouritesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineGenerationFavourites
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    favourited_at = LazyFunction(local_time)
    user_id = None
    result_id = None
