from uuid import uuid4

from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_model_options import DfEngineModelOptions, ModelUsageTypes
from utils import local_time


class DfEngineModelOptionsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineModelOptions
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    last_sync_at = LazyFunction(local_time)
    uid = LazyFunction(lambda: str(uuid4()))
    name = LazyFunction(lambda: f"Model {uuid4().hex[:8]}")
    created = None
    model_id = LazyFunction(lambda: f"vendor/model-{uuid4().hex[:8]}")
    description = Faker("sentence")
    architecture = None
    type = ModelUsageTypes.image
    is_main = False
    is_enabled = False
    is_available = False
    supported_parameters = None
    default_parameters = None
    supports_streaming = None
    supported_resolutions = None
    supported_aspect_ratios = None
    supported_sizes = None
    supported_durations = None
    supported_frame_images = None
    generate_audio = None
    allowed_passthrough_parameters = None
    pricing_skus = None
    pricing = None
    top_provider = None
    knowledge_cutoff = None
    expiration_date = None
