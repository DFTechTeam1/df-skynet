import asyncio
from typing import Any, Optional
from services.api_caller import APICaller
from error import DataValidationError


def validate_total_image_references(
    image_references: list[str], input_references_parameter: Optional[dict[str, Any]] = None
) -> None:
    if not image_references:
        return None

    if input_references_parameter:
        """
        Will be act to references as image generation validation,
        since image model having minimum and maximum value,
        we can validate total image references and model capabilities to take references.
        """
        if len(image_references) > input_references_parameter["max"]:
            raise DataValidationError(
                message="input_references_exceeded",
                error={"references": ["input_references_exceeded"]},
            )

    """
    Fallback is to video generation, since video model doesnt have a total images
    system will not validate total accepted model dan be passed to OpenRouter.
    So system will literally sent whatever references given from user.
    """
    return None


async def validate_image_availability(references: list[str]) -> list[str]:
    """Checks each URL is reachable, then returns `references` as-is — OpenRouter's
    documented schema takes a plain public URL (no base64 data URI support shown),
    and these URLs are already publicly reachable, so no re-encoding is needed."""
    if not references:
        return []

    async def check(url: str) -> Any:
        # HEAD is cheap; some hosts reject it (405/403/501), so fall back to GET on a status error only
        # (not on timeout, which would double the wait).
        res = await api_caller.call("HEAD", url, raise_for_status=False, follow_redirects=True)
        if res.is_error:
            res = await api_caller.call("GET", url, raise_for_status=False, follow_redirects=True)
        return res

    # ponytail: 8s ceiling keeps the request under typical gateway limits; slow CDNs report file_not_found.
    api_caller = APICaller(timeout=8)
    try:
        checks = await asyncio.gather(*(check(url) for url in references), return_exceptions=True)
    finally:
        await api_caller.close()

    errors: dict[str, list[str]] = {}
    for idx, check in enumerate(checks):
        if isinstance(check, Exception) or check.is_error:  # type: ignore
            errors[f"references.{idx}"] = ["file_not_found"]

    if errors:
        raise DataValidationError(message="references_invalid", error=errors)

    return references


def check_supported_params(value: Any, spec: dict[str, Any]) -> str | None:
    match spec.get("type"):
        case "range":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "generation_parameter_must_be_number"
            if spec.get("min") is not None and value < spec["min"]:
                return "generation_parameter_below_minimum"
            if spec.get("max") is not None and value > spec["max"]:
                return "generation_parameter_above_maximum"
            return None
        case "enum":
            return None if value in spec.get("values", []) else "generation_parameter_not_in_enum"
        case "boolean":
            return None if isinstance(value, bool) else "generation_parameter_must_be_boolean"
        case _:
            return None


def validate_image_model_parameter(parameter: dict[str, Any], model: dict[str, Any]) -> None:
    supported_parameter = dict(model.get("supported_parameters") or {})
    supported_parameter.pop("input_references", None)

    errors: dict[str, list[str]] = {}
    for key, value in parameter.items():
        if key == "n":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                errors.setdefault(key, []).append("generation_parameter_below_minimum")
            continue
        spec = supported_parameter.get(key)
        if spec is None:
            errors.setdefault(key, []).append("unsupported_generation_parameter")
            continue
        reason = check_supported_params(value, spec)
        if reason:
            errors.setdefault(key, []).append(reason)

    for key in supported_parameter.keys() - parameter.keys():
        errors.setdefault(key, []).append("generation_parameter_required")

    if errors:
        raise DataValidationError(message="generation_parameters_invalid", error=errors)


def validate_video_model_parameter(parameter: dict[str, Any], model: dict[str, Any]) -> None:
    """Validates a video generation `parameter` dict against the model's declared video
    capabilities (supported_resolutions/aspect_ratios/durations/frame_images, generate_audio),
    before the request is sent to OpenRouter. Mirrors `validate_image_model_parameter` in
    shape and error style."""
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
