from services.mysql.model.df_engine_generations import GenerationKinds
from validations.prompt import PROMPT_INJECTION_THRESHOLD, RELATEDNESS_THRESHOLD, TASK_PROFILES


def _check(scores: dict, type: GenerationKinds) -> str | None:
    """Mirrors the inline checks in rank_prompt, without the network call."""
    if scores["prompt_injection"] >= PROMPT_INJECTION_THRESHOLD:
        return "prompt_injection_detected"
    if scores["relatedness"] < RELATEDNESS_THRESHOLD:
        return "prompt_not_generation_related"
    return None


def _scores(**overrides) -> dict:
    base = dict(prompt_injection=0, relatedness=0)
    base.update(overrides)
    return base


def test_high_prompt_injection_is_rejected_regardless_of_relatedness():
    scores = _scores(prompt_injection=0.9, relatedness=0.9)
    assert _check(scores, GenerationKinds.image) == "prompt_injection_detected"


def test_low_relatedness_is_rejected():
    scores = _scores(relatedness=0.2)
    assert _check(scores, GenerationKinds.storyboard) == "prompt_not_generation_related"


def test_on_topic_prompt_passes():
    scores = _scores(relatedness=0.9)
    assert _check(scores, GenerationKinds.video) is None


def test_threshold_boundaries():
    assert _check(_scores(relatedness=0.5), GenerationKinds.chat) is None
    assert _check(_scores(prompt_injection=0.5), GenerationKinds.chat) == "prompt_injection_detected"


def test_task_profiles_cover_every_generation_kind_used_in_validation():
    assert set(TASK_PROFILES) == {
        GenerationKinds.image,
        GenerationKinds.image_edit,
        GenerationKinds.video,
        GenerationKinds.element,
        GenerationKinds.storyboard,
        GenerationKinds.chat,
        GenerationKinds.enhancer,
    }
