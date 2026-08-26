from uuid import uuid4

from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction, SubFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_prompt_templates import DfEnginePromptTemplatesFactory
from services.mysql.model.df_engine_feature_prompt_mappings import DfEngineFeaturePromptMappings
from utils import local_time


class DfEngineFeaturePromptMappingsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineFeaturePromptMappings
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    uid = LazyFunction(lambda: str(uuid4()))
    df_engine_features = SubFactory(DfEngineFeaturesFactory)
    df_engine_prompt_templates = SubFactory(DfEnginePromptTemplatesFactory)
