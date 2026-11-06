import pytest
from pydantic import ValidationError

from schemas.payload.generations import ImageVideoGenerationPayload as P

BASE = {"prompt": "x", "type": "video", "parameter": {"aspect_ratio": "21:9"}}


@pytest.mark.parametrize("raw, expected", [("#FB542B", "#fb542b"), ("#f00", "#ff0000"), (None, None)])
def test_color_is_normalized(raw, expected):
    frames = [_frame("first_frame")] if raw is not None else []
    assert P(**BASE, default_frame_reference_color=raw, frame_images=frames).default_frame_reference_color == expected


@pytest.mark.parametrize("raw", ["tes", "#zzzzzz", "", 123])
def test_bad_color_raises_translation_key(raw):
    with pytest.raises(ValidationError) as e:
        P(**BASE, default_frame_reference_color=raw, frame_images=[_frame("first_frame")])
    err = e.value.errors()[0]
    assert err["type"] == "value_error" and str(err["ctx"]["error"]) == "default_frame_reference_color_invalid_format"


def _frame(t):
    return {"frame_type": t, "type": "diva", "diva_url": "https://example.com/a.png"}


@pytest.mark.parametrize("frames", [["first_frame"], ["last_frame"]])
def test_color_with_exactly_one_frame_is_valid(frames):
    p = P(**BASE, default_frame_reference_color="#4cfb2b", frame_images=[_frame(t) for t in frames])
    assert p.default_frame_reference_color == "#4cfb2b"


@pytest.mark.parametrize(
    "frames, key",
    [([], "frame_reference_color_requires_one_frame"), (["first_frame", "last_frame"], "no_free_frame_slot")],
)
def test_color_without_exactly_one_frame_is_rejected(frames, key):
    from error import DataValidationError

    with pytest.raises(DataValidationError) as e:
        P(**BASE, default_frame_reference_color="#4cfb2b", frame_images=[_frame(t) for t in frames])
    assert e.value.error == {"default_frame_reference_color": [key]}


def test_no_color_allows_any_frames():
    assert P(**BASE, frame_images=[_frame("first_frame"), _frame("last_frame")]).default_frame_reference_color is None
    assert P(**BASE).default_frame_reference_color is None
