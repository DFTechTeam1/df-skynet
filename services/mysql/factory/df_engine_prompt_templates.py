from uuid import uuid4

from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_prompt_templates import DfEnginePromptTemplates
from utils import local_time


class DfEnginePromptTemplatesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEnginePromptTemplates
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = None
    uid = LazyFunction(lambda: str(uuid4()))
    is_active = True
    name = LazyFunction(lambda: f"Prompt Template {uuid4().hex[:8]}")
    prompt = Faker("paragraph")
    description = Faker("sentence")
    created_by = None
    updated_by = None
