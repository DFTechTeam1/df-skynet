import asyncio
import base64
from typing import Any
from services.api_caller import APICaller
from error import DataValidationError


def check_input_references(supported_parameters: dict[str, Any], references: list[dict[str, Any]]) -> None:
    input_references = supported_parameters.pop("input_references", None) or {"max": 0}
    if references and len(references) > input_references["max"]:
        raise DataValidationError(
            message="input_references_exceeded",
            error={"references": ["input_references_exceeded"]},
        )


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


async def validate_references(references: list[str], supported_parameter: dict[str, Any]) -> list[str]:
    """references: image/stream URLs — verifies each is reachable and returns them as base64
    data URLs, so downstream calls (e.g. OpenRouter) never have to fetch our servers directly."""
    input_references = (supported_parameter or {}).get("input_references")
    if not input_references:
        return []

    count = len(references)
    if count < input_references.get("min", 0):
        raise DataValidationError(
            message="input_references_required",
            error={"references": ["input_references_required"]},
            context={"min": input_references["min"]},
        )
    if count > input_references.get("max", count):
        raise DataValidationError(
            message="input_references_exceeded",
            error={"references": ["input_references_exceeded"]},
        )
    if not references:
        return []

    api_caller = APICaller()
    checks = await asyncio.gather(
        *(api_caller.call("GET", url, raise_for_status=False) for url in references),
        return_exceptions=True,
    )
    await api_caller.close()

    errors: dict[str, list[str]] = {}
    data_urls: list[str] = []
    for idx, check in enumerate(checks):
        if isinstance(check, Exception) or check.is_error:  # type: ignore
            errors[f"references.{idx}"] = ["file_not_found"]
            continue
        content_type = check.headers.get("content-type", "image/png").split(";")[0]  # type: ignore
        data_urls.append(f"data:{content_type};base64,{base64.b64encode(check.content).decode()}")  # type: ignore

    if errors:
        raise DataValidationError(message="references_invalid", error=errors)

    return data_urls


def validate_image_parameter(parameter: dict[str, Any], supported_parameter: dict[str, Any]) -> None:
    supported_parameter = dict(supported_parameter)
    supported_parameter.pop("input_references", None)

    errors: dict[str, list[str]] = {}
    for key, value in parameter.items():
        if key == "n" and value != 1:
            errors.setdefault(key, []).append("generation_parameter_above_maximum")
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
