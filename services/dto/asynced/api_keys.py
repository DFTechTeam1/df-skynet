from typing import Any
from sqlalchemy import func, or_
from services.mysql import query
from services.mysql.model import DfEngineApiKeys, DfEngineGenerations
from services.dto import ConnectionContext
from services.dto.asynced.projects import get_project
from services.dto.asynced.admin_settings import get_project_setting
from services.redis import get_json, set_json
from error import DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize


async def get_api_key(ctx: ConnectionContext, employee_id: int) -> Any:
    cache_key = ctx.key.api_key_main(employee_id)
    data = await get_json(ctx.redis, cache_key)
    if data is not None:
        return data

    api_key = await query(
        ctx.db,
        DfEngineApiKeys,
        filters=(
            DfEngineApiKeys.employee_id == employee_id,
            DfEngineApiKeys.is_main == True,
            DfEngineApiKeys.hash.isnot(None),  # type: ignore
            or_(DfEngineApiKeys.expires_at.is_(None), DfEngineApiKeys.expires_at > local_time()),  # type: ignore
        ),
        fetch_one=True,
    )
    if not api_key:
        raise DataNotFoundError(message="api_key_not_found")

    result = serialize(api_key)
    await set_json(ctx.redis, cache_key, result)
    return result


async def validate_api_key_limitation(ctx: ConnectionContext, project_id: int, api_key_id: int) -> None:
    await get_project(ctx, project_id=project_id)
    setting = await get_project_setting(ctx, project_id=project_id)

    total_usage = await query(
        ctx.db,
        DfEngineGenerations,
        columns=(func.sum(DfEngineGenerations.cost),),  # type: ignore
        filters=(
            DfEngineGenerations.sourceable_id == api_key_id,  # type: ignore
            DfEngineGenerations.sourceable_type == "DfEngineApiKeys",  # type: ignore
        ),
        fetch_one=True,
    )
    total_usage = total_usage or 0

    threshold_amount = setting["token_usage_limit"] * setting["token_limit_threshold"]
    if total_usage >= threshold_amount:
        raise DataValidationError(message="api_key_token_usage_limit_exceeded")
