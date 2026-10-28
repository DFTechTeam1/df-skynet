from uuid import uuid4
from factory.alchemy import SQLAlchemyModelFactory
from factory.declarations import Iterator, LazyFunction
from services.mysql.model.df_engine_api_key_rotation_issues import DfEngineApiKeyRotationIssues
from utils import local_time
from apps.secret import DB_SYNC_URL
from services.mysql import make_sync_session


class DfEngineApiKeyRotationIssuesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineApiKeyRotationIssues
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    uid = LazyFunction(lambda: str(uuid4()))
    old_uid = LazyFunction(lambda: str(uuid4()))
    new_uid = None
    new_key_hash = LazyFunction(lambda: uuid4().hex)
    new_key_value = LazyFunction(lambda: f"sk-{uuid4().hex}")
    issue_type = Iterator(["new_key_db_conflict", "old_key_not_revoked", "archive_failed"])
    detail = None
    resolved_at = None
