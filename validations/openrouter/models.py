import asyncio
import json
from typing import Literal, Any
from sqlalchemy import func, or_
from services.api_caller import APICaller
from sqlalchemy.orm import selectinload
from services.mysql import get_db, query
from services.mysql.model import (
    DfEngineModelOptions,
    DfEngineUploadFiles,
    DfEngineGenerationResults,
    DfEngineGenerations,
    DfEngineProjectSettings,
    DfEngineSettings,
    DfEngineMenus,
    DfEngineMenuFeatureMappings,
    DfEngineFeatures,
    DfEngineFeaturePromptMappings,
    DfEngineApiKeys,
    Projects,
)
from error import DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize
from utils.formatter import format_udin_url


async def get_model(type: Literal["video", "image", "image_edit"], model_uid: str) -> Any:
    async for db in get_db():
        filters = [
            DfEngineModelOptions.uid == model_uid,
            DfEngineModelOptions.type == type,
            DfEngineModelOptions.is_enabled == True,
            DfEngineModelOptions.is_available == True,
            DfEngineModelOptions.deleted_at.is_(None),  # type: ignore
        ]
        if type == "image" or type == "image_edit":
            filters.append(func.json_length(DfEngineModelOptions.supported_parameters) >= 1)  # type: ignore

        model = await query(
            db=db,
            table=DfEngineModelOptions,
            filters=tuple(filters),
            fetch_one=True,
        )

        if not model:
            raise DataNotFoundError(message="model_option_not_found")

        return serialize(model)


async def get_api_key(pic_id: int) -> Any:
    async for db in get_db():
        api_key = await query(
            db=db,
            table=DfEngineApiKeys,
            filters=(
                DfEngineApiKeys.employee_id == pic_id,
                DfEngineApiKeys.is_main == True,
                DfEngineApiKeys.hash.isnot(None),  # type: ignore
                or_(DfEngineApiKeys.expires_at.is_(None), DfEngineApiKeys.expires_at > local_time()),  # type: ignore
            ),
            fetch_one=True,
        )
        if not api_key:
            raise DataNotFoundError(message="api_key_not_found")

        return serialize(api_key)


async def validate_features(menu_uid: str, feature_uid: str) -> tuple[list[dict[str, Any]], int, int]:  # type: ignore
    async for db in get_db():
        menu = await query(
            db=db,
            table=DfEngineMenus,
            filters=(DfEngineMenus.uid == menu_uid, DfEngineMenus.is_active == True),
            options=(
                selectinload(DfEngineMenus.df_engine_menu_feature_mappings)  # type: ignore
                .selectinload(DfEngineMenuFeatureMappings.df_engine_features)  # type: ignore
                .selectinload(DfEngineFeatures.df_engine_feature_prompt_mappings)  # type: ignore
                .selectinload(DfEngineFeaturePromptMappings.df_engine_prompt_templates),  # type: ignore
            ),
            fetch_one=True,
        )
        if not menu:
            raise DataNotFoundError(message="menu_not_found")

        menu_features = {
            str(mapping.df_engine_features.uid): mapping.df_engine_features
            for mapping in menu.df_engine_menu_feature_mappings
            if mapping.df_engine_features
        }

        if feature_uid not in menu_features:
            raise DataValidationError(
                message="feature_not_under_menu", error={"feature_uid": ["feature_not_under_menu"]}
            )

        feature = menu_features[feature_uid]
        prompts = [
            serialize(mapping.df_engine_prompt_templates)
            for mapping in feature.df_engine_feature_prompt_mappings
            if mapping.df_engine_prompt_templates and mapping.df_engine_prompt_templates.is_active
        ]
        return prompts, menu.id, feature.id


def merge_prompt(prompt: str, prompt_templates: list[dict[str, Any]]) -> str:
    return "\n\n".join([prompt, *(template["prompt"] for template in prompt_templates)])


async def validate_prompt_length(prompt: str, project_id: int) -> None:
    async for db in get_db():
        project_setting = await query(
            db=db,
            table=DfEngineProjectSettings,
            filters=(DfEngineProjectSettings.project_id == project_id,),
            fetch_one=True,
        )
        if project_setting:
            max_chars = project_setting.compose_input_max_chars
        else:
            project = await query(
                db=db,
                table=Projects,
                filters=(Projects.id == project_id,),
                fetch_one=True,
            )
            if not project:
                raise DataNotFoundError(message="project_not_found")

            class_limits_row = await query(
                db=db,
                table=DfEngineSettings,
                filters=(DfEngineSettings.key == "project_class_limitations",),
                fetch_one=True,
            )
            if not class_limits_row or not class_limits_row.value:
                raise DataValidationError(message="global_setting_not_configured")
            if project.project_class_id is None:
                raise DataValidationError(message="project_class_not_assigned")

            class_limit = next(
                (item for item in json.loads(class_limits_row.value) if item.get("id") == project.project_class_id),
                None,
            )
            if not class_limit:
                raise DataNotFoundError(message="project_class_limitation_not_found")
            max_chars = class_limit["compose_input_max_chars"]

        length = len(prompt)
        if length > max_chars:
            raise DataValidationError(
                message="prompt_length_exceeded",
                context={"length": length, "max_chars": max_chars},
            )


async def validate_api_key_limitation(project_id: int, api_key_id: int) -> None:
    async for db in get_db():
        project_setting = await query(
            db=db,
            table=DfEngineProjectSettings,
            filters=(DfEngineProjectSettings.project_id == project_id,),
            fetch_one=True,
        )
        if project_setting:
            usage_limit = project_setting.token_usage_limit
            limit_threshold = project_setting.token_limit_threshold
        else:
            project = await query(
                db=db,
                table=Projects,
                filters=(Projects.id == project_id,),
                fetch_one=True,
            )
            if not project:
                raise DataNotFoundError(message="project_not_found")

            class_limits_row = await query(
                db=db,
                table=DfEngineSettings,
                filters=(DfEngineSettings.key == "project_class_limitations",),
                fetch_one=True,
            )
            if not class_limits_row or not class_limits_row.value:
                raise DataValidationError(message="global_setting_not_configured")
            if project.project_class_id is None:
                raise DataValidationError(message="project_class_not_assigned")

            class_limit = next(
                (item for item in json.loads(class_limits_row.value) if item.get("id") == project.project_class_id),
                None,
            )
            if not class_limit:
                raise DataNotFoundError(message="project_class_limitation_not_found")
            usage_limit = class_limit["token_usage_limit"]
            limit_threshold = class_limit["token_limit_threshold"]

        total_usage = await query(
            db=db,
            table=DfEngineGenerations,
            columns=(func.sum(DfEngineGenerations.cost),),
            filters=(
                DfEngineGenerations.sourceable_id == api_key_id,
                DfEngineGenerations.sourceable_type == "DfEngineApiKeys",
            ),
            fetch_one=True,
        )
        total_usage = total_usage or 0

        threshold_amount = usage_limit * limit_threshold
        if total_usage >= threshold_amount:
            raise DataValidationError(
                message="api_key_token_usage_limit_exceeded",
                context={"usage": total_usage, "limit": usage_limit},
            )


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


async def validate_references(references: list[dict[str, Any]], user_id: int, task_id: int):
    upload_uids = set([str(ref["file_uid"]) for ref in references if ref["type"] == "upload"])
    result_uids = set([str(ref["file_uid"]) for ref in references if ref["type"] == "generated"])

    found_uploads: dict[str, tuple[int, str]] = {}
    found_generated: dict[str, tuple[int, str]] = {}
    async for db in get_db():
        if upload_uids:
            file_uploads = await query(
                db=db,
                columns=(
                    DfEngineUploadFiles.id,
                    DfEngineUploadFiles.uid,
                    DfEngineUploadFiles.path,
                ),
                table=DfEngineUploadFiles,
                filters=(
                    DfEngineUploadFiles.uid.in_(upload_uids),  # type: ignore
                    DfEngineUploadFiles.type == "image",
                    DfEngineUploadFiles.created_by == user_id,
                    DfEngineUploadFiles.task_id == task_id,
                ),
            )
            found_uploads = {str(file.uid): (file.id, file.path) for file in file_uploads}

        if result_uids:
            generated_files = await query(
                db=db,
                columns=(
                    DfEngineGenerationResults.id,
                    DfEngineGenerationResults.uid,
                    DfEngineGenerationResults.path,
                ),
                table=DfEngineGenerationResults,
                joins=((DfEngineGenerations, DfEngineGenerations.id == DfEngineGenerationResults.generation_id),),
                filters=(
                    DfEngineGenerationResults.uid.in_(result_uids),  # type: ignore
                    DfEngineGenerationResults.archieved_at.is_(None),  # type: ignore
                    DfEngineGenerationResults.created_by == user_id,
                    DfEngineGenerationResults.is_main == True,
                    DfEngineGenerations.task_id == task_id,
                ),
            )
            found_generated = {str(file.uid): (file.id, file.path) for file in generated_files}

    errors: dict[str, list[str]] = {}
    valid_by_idx: dict[int, dict[str, Any]] = {}
    for idx, ref in enumerate(references):
        file_uid = str(ref["file_uid"])
        found = found_uploads if ref["type"] == "upload" else found_generated
        if file_uid not in found:
            errors[f"references.{idx}.{ref['type']}"] = ["file_not_found"]
            continue
        file_id, path = found[file_uid]
        valid_by_idx[idx] = {"id": file_id, "type": ref["type"], "url": format_udin_url(path)}

    if valid_by_idx:
        api_caller = APICaller()
        checks = await asyncio.gather(
            *(
                api_caller.udin("GET", ref["url"], user_id=user_id, raise_for_status=False)
                for ref in valid_by_idx.values()
            ),
            return_exceptions=True,
        )
        await api_caller.close()
        for idx, check in zip(valid_by_idx, checks):
            if isinstance(check, Exception) or check.is_error:  # type: ignore
                errors[f"references.{idx}.{references[idx]['type']}"] = ["file_not_found"]

    if errors:
        raise DataValidationError(message="references_invalid", error=errors)

    return list(valid_by_idx.values())


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
    type: Literal["video", "image", "image_edit"],
    model_uid: str,
    references: list[dict[str, Any]],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    if type == "image" or type == "image_edit":
        await validate_model_image(model_uid, references, parameters)
    return {}
