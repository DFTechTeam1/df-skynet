import json
from typing import Any, Optional
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, load_only
from apps.secret import OPENROUTER_BASE_URL, OPENROUTER_MANAGEMENT_KEY
from services.mysql import query, query_sync
from services.mysql.model import DfEngineSettings
from utils import local_time

SETTING_CODE = "openrouter_credits"
SETTING_KEY = "credits"
TIMEOUT = httpx.Timeout(5)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {OPENROUTER_MANAGEMENT_KEY}"}


def _parse(res: httpx.Response) -> Optional[dict[str, Any]]:
    if res.is_error:
        return None
    data = (res.json() if res.content else {}).get("data") or {}
    return {"total_credits": data.get("total_credits", 0), "total_usage": data.get("total_usage", 0)}


def _filters() -> tuple[Any, ...]:
    return (DfEngineSettings.code == SETTING_CODE, DfEngineSettings.key == SETTING_KEY)


def _apply(row: Optional[DfEngineSettings], credits: dict[str, Any]) -> DfEngineSettings:
    if row is None:
        return DfEngineSettings(code=SETTING_CODE, key=SETTING_KEY, value=json.dumps(credits))
    row.value, row.updated_at = json.dumps(credits), local_time()
    return row


async def get_stored_credits(db: AsyncSession) -> Optional[dict[str, Any]]:
    row = await query(
        db, DfEngineSettings, options=(load_only(DfEngineSettings.value),), filters=_filters(), fetch_one=True
    )
    return json.loads(row.value) if row and row.value else None


def get_stored_credits_sync(db: Session) -> Optional[dict[str, Any]]:
    row = query_sync(
        db, DfEngineSettings, options=(load_only(DfEngineSettings.value),), filters=_filters(), fetch_one=True
    )
    return json.loads(row.value) if row and row.value else None


async def refresh_credits(db: AsyncSession) -> Optional[dict[str, Any]]:
    """Fetch the live balance and store it in the single `openrouter_credits` row. None on upstream error."""
    async with httpx.AsyncClient(base_url=OPENROUTER_BASE_URL, headers=_headers(), timeout=TIMEOUT) as client:
        credits = _parse(await client.get("/credits"))
    if credits is None:
        return None
    row = (await db.execute(select(DfEngineSettings).where(*_filters()))).scalars().first()
    db.add(_apply(row, credits))
    await db.commit()
    return credits


def refresh_credits_sync(db: Session) -> Optional[dict[str, Any]]:
    with httpx.Client(base_url=OPENROUTER_BASE_URL, headers=_headers(), timeout=TIMEOUT) as client:
        credits = _parse(client.get("/credits"))
    if credits is None:
        return None
    row = db.execute(select(DfEngineSettings).where(*_filters())).scalars().first()
    db.add(_apply(row, credits))
    db.commit()
    return credits
