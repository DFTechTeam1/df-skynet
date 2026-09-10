from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from factory.faker import Faker
from services.mysql.model.df_engine_upload_files import DfEngineUploadFiles, UploadFileTypes
from utils import local_time


class DfEngineUploadFilesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineUploadFiles
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = None
    uid = LazyFunction(lambda: str(uuid4()))
    name = Faker("file_name", category="image")
    type = UploadFileTypes.image
    path = Faker("file_path", depth=2, category="image")
    md5 = LazyFunction(lambda: uuid4().hex)
    size = Faker("random_int", min=1024, max=10_485_760)
    project_id = None
    created_by = None
    updated_by = None
