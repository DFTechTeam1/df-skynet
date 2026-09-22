from schemas.response import OpenrouterRankingResponse
from validations.prompt import rejection_reason


def _scores(**overrides) -> OpenrouterRankingResponse:
    base = dict(prompt_injection=0, image_generation=0, video_generation=0, chat_assistant=0)
    base.update(overrides)
    return OpenrouterRankingResponse(**base)


def test_high_prompt_injection_is_rejected_regardless_of_type():
    scores = _scores(prompt_injection=0.9, image_generation=0.9)
    assert rejection_reason(scores, "image") == "prompt_injection_detected"


def test_low_relevant_dimension_is_rejected():
    scores = _scores(image_generation=0.2, chat_assistant=0.8)
    assert rejection_reason(scores, "image") == "prompt_not_generation_related"


def test_on_topic_prompt_passes():
    scores = _scores(image_generation=0.9, video_generation=0.1)
    assert rejection_reason(scores, "image") is None


def test_threshold_boundaries():
    assert rejection_reason(_scores(image_generation=0.5), "image") is None
    assert rejection_reason(_scores(prompt_injection=0.5), "image") == "prompt_injection_detected"
