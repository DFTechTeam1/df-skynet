from sqlalchemy.orm import load_only
from typing import Any, Optional
from sqlalchemy import func, or_
from services.mysql import query
from services.mysql.model import DfEngineApiKeys, DfEngineGenerations
from services.mysql.model.transfer_team_members import TransferTeamMembers, TRANSFER_STATUS_APPROVED
from services.dto import ConnectionContext
from services.dto.asynced.projects import get_project, get_project_pics
from services.dto.asynced.admin_settings import get_project_setting
from services.redis import get_json, set_json
from log import logging
from error import DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize


async def get_api_key(ctx: ConnectionContext, employee_id: int, raise_if_missing: bool = True) -> Any:
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
        if raise_if_missing:
            raise DataNotFoundError(message="api_key_not_found")
        return None

    result = serialize(api_key)
    ttl = 86400
    if api_key.expires_at:
        ttl = min(ttl, int((api_key.expires_at - local_time()).total_seconds()))
    if ttl > 0:
        await set_json(ctx.redis, cache_key, result, ttl=ttl)
    return result


async def get_api_key_with_lead_fallback(
    ctx: ConnectionContext, candidate_id: Optional[int], lead_pic_id: Optional[int]
) -> Any:
    if candidate_id is not None:
        api_key = await get_api_key(ctx, candidate_id, raise_if_missing=False)
        if api_key:
            return api_key
    if lead_pic_id is not None:
        api_key = await get_api_key(ctx, lead_pic_id, raise_if_missing=False)
        if api_key:
            return api_key
    raise DataNotFoundError(message="employee_api_key_not_resolved")


async def get_employee_api_key(ctx: ConnectionContext, project_id: int, employee_user: dict[str, Any]) -> Any:
    pics = await get_project_pics(ctx, project_id)
    boss_id = employee_user.get("boss_id")
    employee_pics = [record["pic_id"] for record in pics]
    lead_pic_id = next((record["pic_id"] for record in pics if record.get("is_lead")), None)

    if employee_user["id"] in employee_pics:
        """Requester is themselves a direct PIC on this project — use their own key."""
        logging.info(f"api_key resolved via self pic employee_id={employee_user['id']} project_id={project_id}")
        return await get_api_key(ctx, employee_user["id"])

    transfer = await query(
        ctx.db,
        TransferTeamMembers,
        options=(load_only(TransferTeamMembers.requested_by),),
        filters=(
            TransferTeamMembers.project_id == project_id,
            TransferTeamMembers.status == TRANSFER_STATUS_APPROVED,
            TransferTeamMembers.employee_id == employee_user["id"],
        ),
        fetch_one=True,
    )
    if transfer:
        """Staff was transferred onto this project; charge the PIC who approved (requested_by) the
        transfer, falling back to the project's lead PIC if requested_by has no key."""
        logging.info(
            f"api_key resolved via approved transfer employee_id={employee_user['id']} "
            f"requested_by={transfer.requested_by} project_id={project_id}"
        )
        return await get_api_key_with_lead_fallback(ctx, transfer.requested_by, lead_pic_id)

    """Not transferred — try the boss if they're a PIC on this project, else fall back to the lead PIC."""
    candidate = boss_id if boss_id in employee_pics else None
    logging.info(
        f"api_key resolved via boss/lead boss_id={boss_id} candidate={candidate} "
        f"employee_id={employee_user['id']} project_id={project_id}"
    )
    return await get_api_key_with_lead_fallback(ctx, candidate, lead_pic_id)


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
