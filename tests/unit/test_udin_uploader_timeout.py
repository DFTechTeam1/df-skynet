from httpx import Timeout
from services.tasks import udin_uploader


def test_image_uploads_use_a_short_read_timeout():
    """A healthy image upload takes 2-4s, so a hung attempt is retried after 15s instead of ~125s."""
    assert udin_uploader.IMAGE_UPLOAD_TIMEOUT == Timeout(connect=5, read=15, write=15, pool=10)


def test_image_timeout_stays_below_the_task_time_limit_and_the_retry_budget():
    """The cap must be far under soft_time_limit so retries fit inside the task's lifetime."""
    task = udin_uploader.udin_uploader
    assert udin_uploader.IMAGE_UPLOAD_TIMEOUT.read < task.soft_time_limit


def test_openrouter_image_timeout_caps_a_hung_call_well_below_the_default():
    """A hung OpenRouter image call is dropped after 60s (healthy runs take 11-21s) instead of the 120s default."""
    from services.tasks import image_generation

    assert image_generation.OPENROUTER_IMAGE_TIMEOUT == Timeout(connect=10, read=60, write=30, pool=10)
    assert image_generation.OPENROUTER_IMAGE_TIMEOUT.read < image_generation.image_generation.soft_time_limit
