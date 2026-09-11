from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_generations import DfEngineGenerations, GenerationKinds, GenerationStatuses
from utils import local_time


class DfEngineGenerationsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineGenerations
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    kind = GenerationKinds.image
    model_id = None
    menu_id = None
    feature_id = None
    sourceable_id = None
    sourceable_type = "DfEngineApiKeys"
    project_id = None
    task_id = None
    prompt = Faker("sentence")
    status = GenerationStatuses.processing
    response = None
    status_code = None
    token_usage = None
    cost = None
    created_by = None
