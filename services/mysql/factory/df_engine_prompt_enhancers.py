from decimal import Decimal

from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_prompt_enhancers import DfEnginePromptEnhancers
from utils import local_time


class DfEnginePromptEnhancersFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEnginePromptEnhancers
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    model_id = None
    featureable_id = None
    featureable_type = None
    sourceable_id = None
    sourceable_type = None
    project_id = None
    task_id = None
    raw = None
    enhanced = None
    is_processing = True
    response = None
    status_code = None
    token_usage = 0
    cost = Decimal("0.00")
    created_by = None
