from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import Iterator, LazyFunction
from services.mysql.model.df_engine_generation_reconciliation_issues import DfEngineGenerationReconciliationIssues
from utils import local_time


class DfEngineGenerationReconciliationIssuesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineGenerationReconciliationIssues
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    uid = LazyFunction(lambda: str(uuid4()))
    generation_id = None
    upload_id = None
    issue_type = Iterator(["db_commit_failed"])
    detail = None
    resolved_at = None
    resolved_by = None
