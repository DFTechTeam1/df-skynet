import pytest

from error import DataValidationError
from validations.model import validate_video_generation_parameter

PARAM = {"resolution": "720p", "aspect_ratio": "16:9", "duration": 5}


def _model(frames):
    return {
        "supported_resolutions": ["720p"],
        "supported_aspect_ratios": ["16:9"],
        "supported_durations": [5],
        "supported_frame_images": frames,
    }


BOTH = ["first_frame", "last_frame"]


@pytest.mark.parametrize(
    "supplied, expected",
    [(["first_frame"], "last_frame"), (["last_frame"], "first_frame")],
)
def test_color_fills_free_slot_on_two_frame_model(supplied, expected):
    assert validate_video_generation_parameter(PARAM, _model(BOTH), supplied, color="#fb542b") == expected


@pytest.mark.parametrize(
    "frames, supplied, code",
    [
        ([], [], "frame_reference_color_requires_two_frames"),
        (None, [], "frame_reference_color_requires_two_frames"),
        (["first_frame"], [], "frame_reference_color_requires_two_frames"),
        (["last_frame"], [], "frame_reference_color_requires_two_frames"),
        (["first_frame"], ["first_frame"], "frame_reference_color_requires_two_frames"),
        (BOTH, [], "frame_reference_color_requires_one_frame"),
        (BOTH, BOTH, "no_free_frame_slot"),
    ],
)
def test_color_rejected(frames, supplied, code):
    with pytest.raises(DataValidationError) as e:
        validate_video_generation_parameter(PARAM, _model(frames), supplied, color="#fb542b")
    assert e.value.message == code and e.value.error is None


@pytest.mark.parametrize("frames", [[], ["first_frame"]])
def test_no_color_is_unaffected_by_frame_support(frames):
    assert validate_video_generation_parameter(PARAM, _model(frames), []) is None


def _rejects(parameter, key, name=None, model=None, color=None, frame_types=()):
    with pytest.raises(DataValidationError) as e:
        validate_video_generation_parameter(parameter, model or _model(BOTH), list(frame_types), color=color)
    assert e.value.message == key and e.value.error is None
    if name:
        assert e.value.context == {"parameter": name}


@pytest.mark.parametrize("name", ["frame_images", "input_references", "model", "prompt"])
def test_reserved_keys_are_rejected_even_when_a_model_lists_them_as_passthrough(name):
    model = {**_model(BOTH), "allowed_passthrough_parameters": [name]}
    _rejects({**PARAM, name: "x"}, "parameter_unsupported", name, model=model)


def test_passthrough_keys_the_model_allows_are_accepted():
    model = {**_model(BOTH), "allowed_passthrough_parameters": ["seed"]}
    assert validate_video_generation_parameter({**PARAM, "seed": 1}, model, []) is None


@pytest.mark.parametrize("name", ["resolution", "aspect_ratio", "duration"])
def test_required_parameters(name):
    _rejects({k: v for k, v in PARAM.items() if k != name}, "parameter_required", name)


@pytest.mark.parametrize(
    "name, value",
    [
        ("resolution", "8K"),
        ("aspect_ratio", "1:1"),
        ("duration", 9),
        ("duration", 5.0),
        ("generate_audio", None),
        ("generate_audio", "yes"),
        ("generate_audio", True),
    ],
)
def test_invalid_values(name, value):
    _rejects({**PARAM, name: value}, "parameter_invalid", name)


@pytest.mark.parametrize("ratio", ["adaptive", "0:9", "16x9"])
def test_color_needs_a_readable_aspect_ratio(ratio):
    model = {**_model(BOTH), "supported_aspect_ratios": [ratio]}
    parameter = {**PARAM, "aspect_ratio": ratio}
    _rejects(parameter, "parameter_invalid", "aspect_ratio", model=model, color="#fb542b", frame_types=["first_frame"])
    assert validate_video_generation_parameter(parameter, model, ["first_frame"]) is None


def test_unsupported_frames_are_reported_by_index():
    with pytest.raises(DataValidationError) as e:
        validate_video_generation_parameter(PARAM, _model(["first_frame"]), ["first_frame", "last_frame"])
    assert e.value.message == "reference_check_failed"
    assert e.value.error == {"frame_images.1": ["frame_type_not_supported"]}
