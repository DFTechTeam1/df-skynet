import json
from typing import Any, Optional, Union
from uuid import UUID
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from services.mysql import query
from services.mysql.model import (
    DfEngineMenus,
    DfEngineMenuFeatureMappings,
    DfEngineFeatures,
    DfEngineFeaturePromptMappings,
    DfEngineSettings,
    DfEngineProjectSettings,
    DfEngineModelOptions,
    Projects,
)
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.model_management import ModelManagement
from services.redis import get_json, set_json
from services.dto import ConnectionContext
from services.dto.format_response import FeatureableAction, MenuRecord, FeatureRecord, PromptTemplateRecord
from log import logging
from error import DataNotFoundError, DataValidationError
from utils.serializer import serialize

SETTING_CODE = "admin_setting"

PROJECT_SETTING_LIMIT_FIELDS = (
    "token_usage_limit",
    "compose_input_max_chars",
    "storyboard_prompt_chars",
    "max_scene_per_storyboard",
    "max_shot_per_scene",
    "token_limit_threshold",
)


async def get_menu(
    ctx: ConnectionContext,
    user_id: int,
    menu_uid: Optional[UUID] = None,
    feature_uid: Optional[UUID] = None,
    search: Optional[str] = None,
) -> Union[dict[str, Any], list[dict[str, Any]]]:
    menu_key = ctx.key.get_menu(menu_uid, feature_uid, search)
    menu_data = await get_json(ctx.redis, menu_key)
    if menu_data is not None:
        logging.info(f"menu cache hit key={menu_key}")
        return menu_data

    filters = []
    if menu_uid is not None:
        filters.append(DfEngineMenus.uid == str(menu_uid))  # type: ignore
    if search:
        filters.append(DfEngineMenus.name.ilike(f"%{search}%"))  # type: ignore

    menu_feature_mappings = DfEngineMenus.df_engine_menu_feature_mappings  # type: ignore
    if feature_uid is not None:
        menu_feature_mappings = menu_feature_mappings.and_(  # type: ignore
            DfEngineMenuFeatureMappings.df_engine_features.has(DfEngineFeatures.uid == str(feature_uid))  # type: ignore
        )

    menus = await query(
        ctx.db,
        DfEngineMenus,
        filters=tuple(filters),
        options=(
            selectinload(DfEngineMenus.df_engine_generations),  # type: ignore
            selectinload(menu_feature_mappings)  # type: ignore
            .selectinload(DfEngineMenuFeatureMappings.df_engine_features)  # type: ignore
            .selectinload(DfEngineFeatures.df_engine_generations),  # type: ignore
            selectinload(menu_feature_mappings)  # type: ignore
            .selectinload(DfEngineMenuFeatureMappings.df_engine_features)  # type: ignore
            .selectinload(DfEngineFeatures.df_engine_feature_prompt_mappings)  # type: ignore
            .selectinload(DfEngineFeaturePromptMappings.df_engine_prompt_templates),  # type: ignore
        ),
        fetch_one=(menu_uid is not None),
    )
    if not menus:
        raise DataNotFoundError(message="menu_not_found")
    menus = [menus] if menu_uid is not None else menus

    menu_to_features: dict[int, list] = {}
    for menu in menus:
        menu_features = {
            str(mapping.df_engine_features.uid): mapping.df_engine_features
            for mapping in menu.df_engine_menu_feature_mappings
            if mapping.df_engine_features
        }

        if feature_uid is not None:
            feature = menu_features.get(str(feature_uid))
            if not feature:
                if menu_uid is None:
                    continue
                raise DataValidationError(
                    message="feature_not_under_menu", error={"feature_uid": ["feature_not_under_menu"]}
                )
            menu_to_features[menu.id] = [feature]
        else:
            menu_to_features[menu.id] = list(menu_features.values())

    menu_records = []
    for menu in menus:
        features = menu_to_features.get(menu.id)
        if features is None:
            continue

        feature_records = []
        for feature in features:
            feature_data = serialize(feature)
            prompt_templates = []
            for mapping in feature.df_engine_feature_prompt_mappings:
                template = mapping.df_engine_prompt_templates
                if not template or not template.is_active:
                    continue
                template_data = serialize(template)
                prompt_templates.append(
                    PromptTemplateRecord.from_result(
                        template_data, feature.id, FeatureableAction.from_result(template_data, user_id)
                    )
                )
            feature_records.append(
                FeatureRecord.from_result(
                    feature_data,
                    prompt_templates,
                    FeatureableAction.from_result(feature_data, user_id, bool(feature.df_engine_generations)),
                )
            )

        menu_data_item = serialize(menu)
        menu_dict = MenuRecord.from_result(
            menu_data_item,
            feature_records,
            FeatureableAction.from_result(menu_data_item, user_id, bool(menu.df_engine_generations)),
        ).model_dump()
        menu_records.append(menu_dict)

    menu_data = menu_records[0] if menu_uid is not None else menu_records

    await set_json(ctx.redis, menu_key, menu_data)
    logging.info(f"menu cache set key={menu_key}")
    return menu_data


async def get_admin_settings(ctx: ConnectionContext) -> dict[str, Any]:
    settings_key = ctx.key.setting_global()
    settings = await get_json(ctx.redis, settings_key)
    if settings is not None:
        logging.info(f"admin settings cache hit key={settings_key}")
        return settings

    records = await query(ctx.db, DfEngineSettings, filters=(DfEngineSettings.code == SETTING_CODE,))  # type: ignore
    settings = {row.key: (json.loads(row.value) if row.value else None) for row in records}

    await set_json(ctx.redis, settings_key, settings)
    logging.info(f"admin settings cache set key={settings_key}")
    return settings


async def get_project_setting(
    ctx: ConnectionContext, project_id: Optional[int] = None, project_uid: Optional[UUID] = None
) -> dict[str, Any]:
    setting_key = ctx.key.setting_project(project_uid, project_id)
    setting = await get_json(ctx.redis, setting_key)
    if setting is not None:
        logging.info(f"project setting cache hit key={setting_key}")
        return setting

    filters = []
    if project_uid is not None:
        filters.append(Projects.uid == str(project_uid))  # type: ignore
    if project_id is not None:
        filters.append(Projects.id == project_id)  # type: ignore
    project = await query(ctx.db, Projects, filters=tuple(filters), fetch_one=True)
    if not project:
        raise DataNotFoundError(message="project_not_found")

    saved = await query(
        ctx.db,
        DfEngineProjectSettings,
        filters=(DfEngineProjectSettings.project_id == project.id,),  # type: ignore
        fetch_one=True,
    )
    if saved:
        limits = {field: getattr(saved, field) for field in PROJECT_SETTING_LIMIT_FIELDS}
    else:
        if project.project_class_id is None:
            raise DataValidationError(message="project_class_not_assigned")

        class_limits_row = await query(
            ctx.db,
            DfEngineSettings,
            filters=(
                DfEngineSettings.code == SETTING_CODE,  # type: ignore
                DfEngineSettings.key == "project_class_limitations",  # type: ignore
            ),
            fetch_one=True,
        )
        if not class_limits_row or not class_limits_row.value:
            raise DataValidationError(message="global_setting_not_configured")

        class_limitations = json.loads(class_limits_row.value)
        class_limit = next((item for item in class_limitations if item.get("id") == project.project_class_id), None)
        if not class_limit:
            raise DataNotFoundError(message="project_class_limitation_not_found")
        limits = {field: class_limit.get(field) for field in PROJECT_SETTING_LIMIT_FIELDS}

    setting = {"project": project.name, "classification": project.classification, **limits}
    await set_json(ctx.redis, setting_key, setting)
    logging.info(f"project setting cache set key={setting_key}")
    return setting


async def get_model(ctx: ConnectionContext, model_uid: UUID, type: ModelUsageTypes) -> dict[str, Any]:
    model_key = ctx.key.model_option_details(model_uid)
    model = await get_json(ctx.redis, model_key)
    if model is not None and model.get("type") == type:
        logging.info(f"model option cache hit key={model_key}")
        return model

    filters = [
        DfEngineModelOptions.uid == str(model_uid),  # type: ignore
        DfEngineModelOptions.type == type,  # type: ignore
        DfEngineModelOptions.is_enabled == True,  # type: ignore
        DfEngineModelOptions.is_available == True,  # type: ignore
        DfEngineModelOptions.deleted_at.is_(None),  # type: ignore
    ]
    if type == ModelUsageTypes.image:
        filters.append(func.json_length(DfEngineModelOptions.supported_parameters) >= 1)  # type: ignore
    if type == ModelUsageTypes.text:
        filters.append(func.json_length(DfEngineModelOptions.default_parameters) >= 1)  # type: ignore
    if type == ModelUsageTypes.video:
        filters.append(func.json_length(DfEngineModelOptions.supported_resolutions) >= 1)  # type: ignore
        filters.append(func.json_length(DfEngineModelOptions.supported_aspect_ratios) >= 1)  # type: ignore
        filters.append(func.json_length(DfEngineModelOptions.supported_sizes) >= 1)  # type: ignore
        filters.append(func.json_length(DfEngineModelOptions.supported_durations) >= 1)  # type: ignore
        filters.append(func.json_length(DfEngineModelOptions.supported_frame_images) >= 1)  # type: ignore

    row = await query(ctx.db, DfEngineModelOptions, filters=tuple(filters), fetch_one=True)
    if not row:
        raise DataNotFoundError(message="model_option_not_found")

    model = ModelManagement().format(serialize(row))
    await set_json(ctx.redis, model_key, model)
    logging.info(f"model option cache set key={model_key}")
    return model
