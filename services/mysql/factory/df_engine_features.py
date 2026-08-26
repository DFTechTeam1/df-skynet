from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction, RelatedFactory
from factory.faker import Faker
from services.mysql.model.df_engine_features import DfEngineFeatures
from utils import local_time


class DfEngineFeaturesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineFeatures
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = None
    uid = LazyFunction(lambda: str(uuid4()))
    name = LazyFunction(lambda: f"Feature {uuid4().hex[:8]}")
    description = Faker("sentence")
    is_active = True
    created_by = None
    updated_by = None
    df_engine_feature_prompt_mapping = RelatedFactory(
        "services.mysql.factory.df_engine_feature_prompt_mappings.DfEngineFeaturePromptMappingsFactory",
        factory_related_name="df_engine_features",
    )
