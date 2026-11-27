import re
import asyncio
from typing import Any, Optional
from error import DataValidationError
from services.api_caller import APICaller


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


def validate_image_generation_parameter(parameter: dict[str, Any], supported_parameters: dict[str, Any]) -> None:
    """Image generation and edit rules: nothing unsupported, nothing missing, every value allowed.
    `n` is a whole number of at least 1 within the model's own limit; a model that declares no `n` only allows 1.
    Raises on the first problem, with a message only (no `error` fields)."""
    specs = {name: spec for name, spec in supported_parameters.items() if name != "input_references"}

    for name, value in parameter.items():
        if name == "n":
            if type(value) is not int or value < 1 or (name not in specs and value != 1):
                raise DataValidationError(message="parameter_invalid", context={"parameter": name})
            if name not in specs:
                continue
        if name not in specs:
            raise DataValidationError(message="parameter_unsupported", context={"parameter": name})
        if check_supported_params(value, specs[name]):
            raise DataValidationError(message="parameter_invalid", context={"parameter": name})

    for name in specs:
        if name not in parameter:
            raise DataValidationError(message="parameter_required", context={"parameter": name})


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


# Keys the engine fills in itself. `parameter` is merged into the provider payload, so these are never accepted,
# even when a model lists them as passthrough.
RESERVED_VIDEO_PARAMETERS = {"model", "prompt", "frame_images", "input_references"}
VIDEO_PARAMETERS = {"resolution", "aspect_ratio", "duration", "generate_audio"}
FRAME_COLOR_ASPECT_RATIO = re.compile(r"[1-9]\d*:[1-9]\d*")


def validate_video_generation_parameter(
    parameter: dict[str, Any], model: dict[str, Any], frame_types: list[str], color: Optional[str] = None
) -> Optional[str]:
    """Video generation rules, checked against the model's capabilities before anything is paid for.

    `frame_types` are the types of the frame references the user sent, in their order. With a `color`, the
    model must support both first and last frames and the user must send exactly one of them; the other
    one's type is returned, for the color to fill. Raises on the first problem. Only unsupported frames
    use `error`, one entry per frame index.
    """
    supported_frames = model.get("supported_frame_images") or []

    color_frame_type: Optional[str] = None
    if color is not None:
        if not {"first_frame", "last_frame"} <= set(supported_frames):
            raise DataValidationError(message="frame_reference_color_requires_two_frames")
        if not frame_types:  # the color only fills the *other* slot, so the user must pick one frame first
            raise DataValidationError(message="frame_reference_color_requires_one_frame")
        color_frame_type = next((t for t in supported_frames if t not in frame_types), None)
        if color_frame_type is None:  # user already supplied both frames
            raise DataValidationError(message="no_free_frame_slot")

    unsupported_frames = {
        f"frame_images.{index}": ["frame_type_not_supported"]
        for index, frame_type in enumerate(frame_types)
        if frame_type not in supported_frames
    }
    if unsupported_frames:
        raise DataValidationError(message="reference_check_failed", error=unsupported_frames)

    allowed = (VIDEO_PARAMETERS | set(model.get("allowed_passthrough_parameters") or [])) - RESERVED_VIDEO_PARAMETERS
    for name in parameter:
        if name not in allowed:
            raise DataValidationError(message="parameter_unsupported", context={"parameter": name})

    for name, supported_column in (
        ("resolution", "supported_resolutions"),
        ("aspect_ratio", "supported_aspect_ratios"),
        ("duration", "supported_durations"),
    ):
        value = parameter.get(name)
        if value is None:
            raise DataValidationError(message="parameter_required", context={"parameter": name})
        wrong_type = name == "duration" and type(value) is not int
        if wrong_type or value not in (model.get(supported_column) or []):
            raise DataValidationError(message="parameter_invalid", context={"parameter": name})

    if "generate_audio" in parameter:
        audio = parameter["generate_audio"]
        if not isinstance(audio, bool) or (audio and not model.get("generate_audio")):
            raise DataValidationError(message="parameter_invalid", context={"parameter": "generate_audio"})

    # The color image is drawn from the aspect ratio after the paid checks, so it must be readable as W:H
    if color is not None and not FRAME_COLOR_ASPECT_RATIO.fullmatch(str(parameter["aspect_ratio"])):
        raise DataValidationError(message="parameter_invalid", context={"parameter": "aspect_ratio"})

    return color_frame_type
