import random
from typing import Any, Literal, Optional


def parse_image_payload(
    model_id: str,
    prompt: str,
    parameter: dict[str, Any],
    references: list[str],
) -> dict[str, Any]:
    parameter = dict(parameter)
    if parameter.pop("seed", False):
        parameter["seed"] = random.randint(0, 100000)

    if "output_compression" in parameter:
        parameter["output_format"] = "jpeg"

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
    return None


def parse_generation_payload(
    type: Literal["image", "video"],
    model_id: str,
    prompt: str,
    parameter: dict[str, Any],
    references: list[str],
) -> Optional[dict[str, Any]]:
    if type == "video":
        return parse_video_payload(model_id, prompt, parameter, references)
    return parse_image_payload(model_id, prompt, parameter, references)
