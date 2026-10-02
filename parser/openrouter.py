import random
from typing import Any, Literal, Optional
from log import logging


def parse_openrouter_payload(
    model_id: str,
    prompt: str,
    parameter: dict[str, Any],
    references: list[str],
    type: Literal["image", "video"],
    frame_images: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Builds the OpenRouter generation request payload, applying each type's own
    OpenRouter-specific transforms before sending (image: seed/output_compression;
    video: frame_images reshaped into OpenRouter's {frame_type, type, image_url} form).
    `frame_images` is the already-resolved [{frame_type, image}] list (see
    ImageVideoGenerationPayload.frame_images) — not read from `parameter`."""
    parameter = dict(parameter)

    if type == "image":
        if parameter.pop("seed", False):
            parameter["seed"] = random.randint(0, 100000)
        if "output_compression" in parameter:
            parameter["output_format"] = "jpeg"

    payload: dict[str, Any] = {"model": model_id, "prompt": prompt, **parameter}

    if frame_images:
        payload["frame_images"] = [
            {"frame_type": frame["frame_type"], "type": "image_url", "image_url": {"url": frame["image"]}}
            for frame in frame_images
        ]
    if references:
        payload["input_references"] = [{"type": "image_url", "image_url": {"url": url}} for url in references]

    logging.info(
        f"parsed openrouter payload type={type} model={model_id} references={len(references)} "
        f"frame_images={len(frame_images or [])} parameter_keys={sorted(parameter.keys())}"
    )
    return payload
