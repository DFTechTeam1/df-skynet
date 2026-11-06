import pytest

from error import DataValidationError
from validations.model import validate_video_model_parameter

PARAM = {"resolution": "720p", "aspect_ratio": "16:9", "duration": 5}


def _model(frames):
    return {
        "supported_resolutions": ["720p"],
        "supported_aspect_ratios": ["16:9"],
        "supported_durations": [5],
        "supported_frame_images": frames,
    }


def _frame(t):
    return {"frame_type": t, "image": "http://x/y.png"}


BOTH = ["first_frame", "last_frame"]


@pytest.mark.parametrize(
    "supplied, expected",
    [(["first_frame"], "last_frame"), (["last_frame"], "first_frame")],
)
def test_color_fills_free_slot_on_two_frame_model(supplied, expected):
    p = {**PARAM, "frame_images": [_frame(t) for t in supplied]}
    assert validate_video_model_parameter(p, _model(BOTH), color="#fb542b") == expected


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
    p = {**PARAM, "frame_images": [_frame(t) for t in supplied]}
    with pytest.raises(DataValidationError) as e:
        validate_video_model_parameter(p, _model(frames), color="#fb542b")
    assert e.value.error["default_frame_reference_color"] == [code]


@pytest.mark.parametrize("frames", [[], ["first_frame"]])
def test_no_color_is_unaffected_by_frame_support(frames):
    assert validate_video_model_parameter(PARAM, _model(frames)) is None
