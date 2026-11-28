import pytest
from schemas.format.model_options import ModelRecord


def _record(type, pricing_skus):
    return ModelRecord.model_construct(type=type, pricing_skus=pricing_skus)


@pytest.mark.parametrize(
    "type,pricing_skus,expected",
    [
        ("video", {"video_tokens": "1", "video_tokens_with_video_input": "1"}, True),
        ("video", {"video_tokens_1080p_with_video_input": "1"}, False),
        ("video", {"duration_seconds": "1"}, False),
        ("video", None, False),
        ("text", {"video_tokens_with_video_input": "1"}, False),
    ],
)
def test_is_supported_video_reference_is_in_the_response(type, pricing_skus, expected):
    assert _record(type, pricing_skus).model_dump(warnings=False)["is_supported_video_reference"] is expected
