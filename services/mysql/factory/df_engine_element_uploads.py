from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql import make_sync_session
from services.mysql.model.df_engine_element_uploads import DfEngineElementUploads
from utils import local_time


class DfEngineElementUploadsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineElementUploads
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    uid = LazyFunction(lambda: str(uuid4()))
    created_at = LazyFunction(local_time)
    updated_at = None
    name = Faker("file_name", category="image")
    path = Faker("file_path", depth=2, category="image")
    md5 = LazyFunction(lambda: uuid4().hex)
    size = Faker("random_int", min=1024, max=10_485_760)
    element_id = None
    project_id = None
    created_by = None
    updated_by = None
