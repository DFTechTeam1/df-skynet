from typing import Any
from error import DataValidationError


def validate_video_parameter(parameter: dict[str, Any], model: dict[str, Any]) -> None:
    """Validates a video generation `parameter` dict against a model's declared
    video capabilities, before the request is sent to OpenRouter. Mirrors
    `validate_image_parameter` (validations/model.py) in shape and error style.

    ponytail: does not validate `references` (input_references) count/acceptance —
    OpenRouter only exposes a boolean `supports_image_reference` per model, not a
    count, and that flag isn't synced into DfEngineModelOptions yet. Add a
    supports_image_reference column + sync it, then gate on it here, once that
    data exists."""
    errors: dict[str, list[str]] = {}

    resolution = parameter.get("resolution")
    if resolution is None:
        errors.setdefault("resolution", []).append("generation_parameter_required")
    elif resolution not in (model.get("supported_resolutions") or []):
        errors.setdefault("resolution", []).append("generation_parameter_not_in_enum")

    aspect_ratio = parameter.get("aspect_ratio")
    if aspect_ratio is None:
        errors.setdefault("aspect_ratio", []).append("generation_parameter_required")
    elif aspect_ratio not in (model.get("supported_aspect_ratios") or []):
        errors.setdefault("aspect_ratio", []).append("generation_parameter_not_in_enum")

    duration = parameter.get("duration")
    if duration is None:
        errors.setdefault("duration", []).append("generation_parameter_required")
    elif not isinstance(duration, int) or isinstance(duration, bool):
        errors.setdefault("duration", []).append("generation_parameter_must_be_number")
    elif duration not in (model.get("supported_durations") or []):
        errors.setdefault("duration", []).append("generation_parameter_not_in_enum")

    frame_images = parameter.get("frame_images")
    if frame_images is not None:
        supported_frame_images = model.get("supported_frame_images") or []
        if not isinstance(frame_images, list):
            errors.setdefault("frame_images", []).append("generation_parameter_must_be_list")
        else:
            for idx, frame in enumerate(frame_images):
                if not isinstance(frame, dict):
                    errors.setdefault(f"frame_images.{idx}", []).append("generation_parameter_invalid")
                    continue
                if frame.get("frame_type") not in supported_frame_images:
                    errors.setdefault(f"frame_images.{idx}.frame_type", []).append("generation_parameter_not_in_enum")
                if not frame.get("image"):
                    errors.setdefault(f"frame_images.{idx}.image", []).append("frame_image_required")

    generate_audio = parameter.get("generate_audio")
    if generate_audio is not None:
        if not isinstance(generate_audio, bool):
            errors.setdefault("generate_audio", []).append("generation_parameter_must_be_boolean")
        elif generate_audio and not model.get("generate_audio"):
            errors.setdefault("generate_audio", []).append("generation_parameter_not_supported")

    allowed_passthrough = set(model.get("allowed_passthrough_parameters") or [])
    known_keys = {"resolution", "aspect_ratio", "duration", "frame_images", "generate_audio"}
    for key in parameter.keys() - known_keys - allowed_passthrough:
        errors.setdefault(key, []).append("unsupported_generation_parameter")

    if errors:
        raise DataValidationError(message="generation_parameters_invalid", error=errors)


def parse_video_generation_payload(
    model_id: str, prompt: str, parameter: dict[str, Any], references: list[str]
) -> dict[str, Any]:
    """Builds the OpenRouter `POST /videos` payload from an already-`validate_video_parameter`-checked
    `parameter` dict. Mirrors `parse_image_payload` (parser/openrouter.py): most parameter keys pass
    through as-is (resolution, aspect_ratio, duration, generate_audio, passthrough extras); `references`
    becomes `input_references`. `frame_images` entries are our simple {frame_type, image: url} shape —
    OpenRouter needs each one as {frame_type, type: "image_url", image_url: {url}}, so that's translated
    here rather than pushed onto every caller."""
    parameter = dict(parameter)
    frame_images = parameter.pop("frame_images", None)

    payload: dict[str, Any] = {"model": model_id, "prompt": prompt, **parameter}
    if frame_images:
        payload["frame_images"] = [
            {"frame_type": frame["frame_type"], "type": "image_url", "image_url": {"url": frame["image"]}}
            for frame in frame_images
        ]
    if references:
        payload["input_references"] = [{"type": "image_url", "image_url": {"url": url}} for url in references]
    return payload


if __name__ == "__main__":
    seedance_2_mini = {
        "supported_resolutions": ["480p", "720p"],
        "supported_aspect_ratios": ["1:1", "3:4", "9:16", "4:3", "16:9", "21:9", "9:21"],
        "supported_durations": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
        "supported_frame_images": ["first_frame", "last_frame"],
        "generate_audio": True,
        "allowed_passthrough_parameters": ["watermark", "req_key", "return_last_frame"],
    }

    validate_video_parameter(
        {
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "duration": 5,
            "frame_images": [{"frame_type": "first_frame", "image": "https://example.com/a.png"}],
            "generate_audio": True,
            "watermark": True,
        },
        seedance_2_mini,
    )

    try:
        validate_video_parameter({"resolution": "4K", "aspect_ratio": "16:9", "duration": 5}, seedance_2_mini)
        assert False, "expected DataValidationError for unsupported resolution"
    except DataValidationError as exc:
        assert "generation_parameter_not_in_enum" in exc.error["resolution"]

    try:
        validate_video_parameter({"resolution": "720p", "aspect_ratio": "16:9"}, seedance_2_mini)
        assert False, "expected DataValidationError for missing duration"
    except DataValidationError as exc:
        assert "generation_parameter_required" in exc.error["duration"]

    try:
        validate_video_parameter(
            {"resolution": "720p", "aspect_ratio": "16:9", "duration": 5, "seed": 42}, seedance_2_mini
        )
        assert False, "expected DataValidationError for unknown parameter"
    except DataValidationError as exc:
        assert "unsupported_generation_parameter" in exc.error["seed"]

    payload = parse_video_generation_payload(
        "bytedance/seedance-2.0-mini",
        "a cat riding a skateboard",
        {
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "duration": 5,
            "frame_images": [
                {"frame_type": "first_frame", "image": "https://example.com/first.png"},
                {"frame_type": "last_frame", "image": "https://example.com/last.png"},
            ],
        },
        ["https://example.com/ref.png"],
    )
    assert payload == {
        "model": "bytedance/seedance-2.0-mini",
        "prompt": "a cat riding a skateboard",
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "duration": 5,
        "frame_images": [
            {
                "frame_type": "first_frame",
                "type": "image_url",
                "image_url": {"url": "https://example.com/first.png"},
            },
            {
                "frame_type": "last_frame",
                "type": "image_url",
                "image_url": {"url": "https://example.com/last.png"},
            },
        ],
        "input_references": [{"type": "image_url", "image_url": {"url": "https://example.com/ref.png"}}],
    }

    print("all checks passed")
