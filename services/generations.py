from typing import Any, Optional
from uuid import UUID
from error import DataNotFoundError, DataValidationError
from schemas.payload.generations import GenerationReferences
from services.files import FileCtx, FilesService
from services.mysql import query
from services.mysql.model import (
    DfEngineFeaturePromptMappings,
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    DfEngineModelOptions,
    DfEnginePromptTemplates,
)
from services.mysql.model.df_engine_model_options import ModelUsageTypes


class GenerationsService:
    async def resolve_model(self, ctx: FileCtx, model_uid: UUID, gen_type: str) -> Any:
        model = await query(
            db=ctx.db,
            table=DfEngineModelOptions,
            filters=(
                DfEngineModelOptions.uid == str(model_uid),
                DfEngineModelOptions.is_available.is_(True),  # type: ignore
                DfEngineModelOptions.is_enabled.is_(True),  # type: ignore
                DfEngineModelOptions.type == ModelUsageTypes(gen_type),
            ),
            fetch_one=True,
        )
        if model is None:
            raise DataNotFoundError(message="model_option_not_found")
        return model

    async def resolve_menu_and_features(
        self, ctx: FileCtx, menu_uid: UUID, feature_uids: list[UUID]
    ) -> tuple[Any, list[Any]]:
        """No is_active filter here - menus/features are validated for existence only. Only
        df_engine_prompt_templates (fetch_active_prompt_templates) filters on is_active, since
        that's the data actually injected into the user's prompt."""
        menu = await query(
            db=ctx.db, table=DfEngineMenus, filters=(DfEngineMenus.uid == str(menu_uid),), fetch_one=True
        )
        if menu is None:
            raise DataNotFoundError(message="menu_not_found")

        feature_uid_strings = [str(uid) for uid in feature_uids]
        matched = await query(
            db=ctx.db,
            table=DfEngineFeatures,
            joins=((DfEngineMenuFeatureMappings, DfEngineMenuFeatureMappings.feature_id == DfEngineFeatures.id),),
            filters=(
                DfEngineMenuFeatureMappings.menu_id == menu.id,
                DfEngineFeatures.uid.in_(feature_uid_strings),  # type: ignore
            ),
        )
        by_uid = {feature.uid: feature for feature in matched}

        errors: dict[str, list[str]] = {}
        features = []
        for idx, feature_uid in enumerate(feature_uid_strings):
            feature = by_uid.get(feature_uid)
            if feature is None:
                errors[f"feature_uids.{idx}"] = ["feature_not_exists"]
            else:
                features.append(feature)
        if errors:
            raise DataValidationError(message="feature_uids_invalid", error=errors)
        return menu, features

    async def fetch_active_prompt_templates(self, ctx: FileCtx, feature_ids: list[int]) -> list[dict[str, Any]]:
        rows = await query(
            db=ctx.db,
            table=DfEnginePromptTemplates,
            columns=(
                DfEngineFeaturePromptMappings.feature_id,
                DfEnginePromptTemplates.uid,
                DfEnginePromptTemplates.name,
                DfEnginePromptTemplates.prompt,
            ),
            joins=(
                (
                    DfEngineFeaturePromptMappings,
                    DfEngineFeaturePromptMappings.template_id == DfEnginePromptTemplates.id,
                ),
            ),
            filters=(
                DfEngineFeaturePromptMappings.feature_id.in_(feature_ids),  # type: ignore
                DfEnginePromptTemplates.is_active.is_(True),  # type: ignore
            ),
        )
        return [{"feature_id": row.feature_id, "uid": row.uid, "name": row.name, "prompt": row.prompt} for row in rows]

    async def resolve_references(self, ctx: FileCtx, references: list[GenerationReferences]) -> list[dict[str, Any]]:
        file_service = FilesService()
        errors: dict[str, list[str]] = {}
        resolved: list[dict[str, Any]] = []
        for idx, reference in enumerate(references):
            if reference.type == "diva":
                resolved.append({"type": reference.type, "url": str(reference.format_udin_url)})
                continue
            try:
                file = await file_service.get_file_detail(ctx, str(reference.file_uid), kind=reference.type)
                resolved.append({"type": reference.type, "url": file["path"]})
            except DataNotFoundError:
                errors[f"references.{idx}"] = ["file_not_found"]
        if errors:
            raise DataValidationError(message="references_invalid", error=errors)
        return resolved

    def validate_parameters(self, model_option: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        """Every param the caller sends must be declared in the model's `supported_parameters`
        schema, and match the type/range/enum/boolean that schema specifies."""
        supported = model_option.get("supported_parameters") or {}
        errors: dict[str, list[str]] = {}
        for key, value in parameters.items():
            spec = supported.get(key)
            if spec is None:
                errors[f"parameter.{key}"] = ["not a supported parameter for this model"]
                continue
            reason = self.check_supported_parameter(value, spec)
            if reason:
                errors[f"parameter.{key}"] = [reason]
        if errors:
            raise DataValidationError(message="parameter_invalid", error=errors)
        return parameters

    def check_supported_parameter(self, value: Any, spec: dict[str, Any]) -> Optional[str]:
        spec_type = spec.get("type")
        if spec_type == "enum":
            return None if value in spec.get("values", []) else self.enum_message(spec.get("values", []))
        if spec_type == "range":
            if not self.is_of_type(value, (int, float)):
                return "must be a number"
            minimum, maximum = spec.get("min"), spec.get("max")
            if minimum is not None and value < minimum:
                return f"must be >= {minimum}"
            if maximum is not None and value > maximum:
                return f"must be <= {maximum}"
            return None
        if spec_type == "boolean":
            return None if self.is_of_type(value, bool) else "must be a bool"
        return None

    def enum_message(self, allowed_values: list[Any]) -> str:
        if not allowed_values:
            return "not supported by this model"
        return f"must be one of: {', '.join(str(v) for v in allowed_values)}"

    def is_of_type(self, value: Any, expected: type | tuple[type, ...]) -> bool:
        """isinstance() with bool excluded from the int/float branch (bool is a subclass of int
        in Python, but a stray `true` shouldn't silently pass a numeric parameter check)."""
        if isinstance(value, bool):
            return expected is bool or (isinstance(expected, tuple) and bool in expected)
        return isinstance(value, expected)
