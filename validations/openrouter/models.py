from typing import Literal, Any
from sqlalchemy import func
from services.mysql import get_db, query
from services.mysql.model import DfEngineModelOptions, DfEngineUploadFiles, DfEngineGenerationResults
from services.generations import GenerationsService
from error import DataNotFoundError, DataValidationError
from utils.serializer import serialize


async def get_model(type: Literal["video", "image"], model_uid: str) -> Any:
    async for db in get_db():
        model = await query(
            db=db,
            table=DfEngineModelOptions,
            filters=(
                DfEngineModelOptions.uid == model_uid,
                DfEngineModelOptions.type == type,
                DfEngineModelOptions.is_enabled == True,
                DfEngineModelOptions.is_available == True,
                func.json_length(DfEngineModelOptions.supported_parameters) >= 1,
            ),
            fetch_one=True,
        )

        if not model:
            raise DataNotFoundError(message="model_option_not_found")

        return serialize(model)


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


async def validate_references(references: list[dict[str, Any]], user_id: int):
    upload_uids = set([str(ref["file_uid"]) for ref in references if ref["type"] == "upload"])
    result_uids = set([str(ref["file_uid"]) for ref in references if ref["type"] == "generated"])

    found_uploads: set[str] = set()
    found_generated: set[str] = set()
    async for db in get_db():
        file_uploads = await query(
            db=db,
            columns=(
                DfEngineUploadFiles.uid,
                DfEngineUploadFiles.path,
            ),
            table=DfEngineUploadFiles,
            filters=(
                DfEngineUploadFiles.uid.in_(upload_uids),  # type: ignore
                DfEngineUploadFiles.type == "image",
                DfEngineUploadFiles.created_by == user_id,
            ),
        )

        generated_files = await query(
            db=db,
            columns=(
                DfEngineGenerationResults.uid,
                DfEngineGenerationResults.path,
            ),
            table=DfEngineGenerationResults,
            filters=(
                DfEngineGenerationResults.uid.in_(result_uids),
                DfEngineGenerationResults.archieved_at.is_(None),
                DfEngineGenerationResults.created_by == user_id,
                DfEngineGenerationResults.is_main == True,
            ),
        )

        found_uploads = {str(file.uid) for file in file_uploads}
        found_generated = {str(file.uid) for file in generated_files}

    errors: dict[str, list[str]] = {}
    for idx, ref in enumerate(references):
        if ref["type"] == "upload" and str(ref["file_uid"]) not in found_uploads:
            errors[f"references.{idx}.upload"] = ["file_not_found"]
        elif ref["type"] == "generated" and str(ref["file_uid"]) not in found_generated:
            errors[f"references.{idx}.generated"] = ["file_not_found"]

    if errors:
        raise DataValidationError(message="references_invalid", error=errors)


async def validate_model_image(model_uid: str, references: list[dict[str, Any]], parameters: dict[str, Any]):
    errors = {}
    model = await get_model("image", model_uid)
    supported_parameters = dict(model.get("supported_parameters") or {})
    check_input_references(supported_parameters, references)
    for key, value in parameters.items():
        spec = supported_parameters.get(key)
        if spec is None:
            errors.setdefault(key, []).append("unsupported_generation_parameter")
            continue
        reason = check_supported_params(value, spec)
        if reason:
            errors.setdefault(key, []).append(reason)

    for key in supported_parameters.keys() - parameters.keys():
        errors.setdefault(key, []).append("generation_parameter_required")

    if errors:
        raise DataValidationError(message="generation_parameters_invalid", error=errors)


async def validate_model_params(
    type: Literal["video", "image"], model_uid: str, references: list[dict[str, Any]], parameters: dict[str, Any]
) -> dict[str, Any]:
    if type == "image":
        await validate_model_image(model_uid, references, parameters)
    return {}
