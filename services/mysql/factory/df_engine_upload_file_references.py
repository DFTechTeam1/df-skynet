from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_upload_file_references import DfEngineUploadFileReferences
from utils import local_time


class DfEngineUploadFileReferencesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineUploadFileReferences
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    generation_id = None
    file_id = None
