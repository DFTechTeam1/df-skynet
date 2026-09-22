from services.celery_app import celery_app
from services.tasks.base import GenerationTask


@celery_app.task(bind=True, base=GenerationTask, name="df_engine.video_generation")
def video_generation(self, generation_id: int, *args, **kwargs):
    raise NotImplementedError("video_generation is not implemented yet")
