from typing import Any, Literal, Optional


def parse_image_payload(
    model_id: str,
    prompt: str,
    parameter: dict[str, Any],
    references: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model_id, "prompt": prompt, **parameter}
    if references:
        payload["input_references"] = [{"type": "image_url", "image_url": {"url": url}} for url in references]
    return payload


def parse_video_payload(
    model_id: str,
    prompt: str,
    parameter: dict[str, Any],
    references: list[str],
) -> Optional[dict[str, Any]]:
    # POST /api/v1/videos — fields: model, prompt, duration, resolution, aspect_ratio,
    # size, seed, generate_audio, callback_url, provider. duration/aspect_ratio must be
    # validated against the model's supported_durations/supported_aspect_ratios.
    # Not implemented yet — video generation isn't live.
    return None


def parse_generation_payload(
    type: Literal["image", "video", "image_edit"],
    model_id: str,
    prompt: str,
    parameter: dict[str, Any],
    references: list[str],
) -> Optional[dict[str, Any]]:
    if type == "video":
        return parse_video_payload(model_id, prompt, parameter, references)
    return parse_image_payload(model_id, prompt, parameter, references)
