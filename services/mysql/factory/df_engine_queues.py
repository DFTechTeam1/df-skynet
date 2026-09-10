from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import Iterator, LazyFunction
from services.mysql.model.df_engine_queues import DfEngineQueues, QueueEventTypes
from utils import local_time


class DfEngineQueuesFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineQueues
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    task_uid = LazyFunction(lambda: str(uuid4()))
    generation_id = None
    queue_name = Iterator(["generate_images", "generate_videos"])
    event_type = QueueEventTypes.enqueued
    attempt = 1
    detail = None
