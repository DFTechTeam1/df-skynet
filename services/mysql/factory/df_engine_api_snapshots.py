from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction, Sequence
from factory.faker import Faker
from services.mysql.model.df_engine_api_snapshots import DfEngineApiSnapshots
from utils import local_time


class DfEngineApiSnapshotsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineApiSnapshots
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = None
    expires_at = None
    limit = None
    limit_reset = None
    uid = LazyFunction(lambda: str(uuid4()))
    key = LazyFunction(lambda: f"sk-{uuid4().hex}")
    hash = None
    name = Sequence(lambda n: f"API Snapshot {n}")
    description = Faker("sentence")
    employee_id = None
    employee_name = None
    created_by = None
    updated_by = None
