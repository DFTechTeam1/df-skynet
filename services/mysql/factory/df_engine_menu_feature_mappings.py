from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction, SubFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.model.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappings
from utils import local_time


class DfEngineMenuFeatureMappingsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineMenuFeatureMappings
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    uid = LazyFunction(lambda: str(uuid4()))
    df_engine_menus = SubFactory(DfEngineMenusFactory)
    df_engine_features = SubFactory(DfEngineFeaturesFactory)
