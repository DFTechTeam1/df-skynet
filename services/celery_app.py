from celery import Celery
from apps.secret import CELERY_BROKER_URL, CELERY_RESULT_BACKEND


celery_app = Celery(
    "df_engine",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "services.tasks.image_generation",
        "services.tasks.video_generation",
        "services.tasks.udin_uploader",
    ],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 120},
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Jakarta",
    enable_utc=True,
    task_routes={
        "df_engine.image_generation": {"queue": "image_generation"},
        "df_engine.video_generation": {"queue": "video_generation"},
        "df_engine.udin_uploader": {"queue": "udin_uploads"},
    },
)
