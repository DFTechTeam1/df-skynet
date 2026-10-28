from sqlalchemy.orm import load_only
import sys
import json
import asyncio
import traceback
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from log import logging
from apps.secret import DB_ASYNC_URL, ERP_EMAIL, ERP_PASSWORD, LOGIN_URL, BASE_URL
from services.api_caller import APICaller
from services.mysql import engine, make_session, query
from services.mysql.model import DfEngineModelOptions, DfEngineSettings
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.redis import client as redis_client, delete_pattern, CacheKeys
from utils import local_time

SETTING_CODE = "admin_setting"
ENABLE = {
    ModelUsageTypes.text: ["google", "openai"],
    ModelUsageTypes.image: ["google"],
    ModelUsageTypes.video: ["alibaba", "seedance"],
}


async def sync_models() -> bool:
    """Log in, then hit POST /models so df_engine_model_options mirrors the OpenRouter catalog."""
    if not (LOGIN_URL and ERP_EMAIL and ERP_PASSWORD):
        logging.warning("seeder=model sync skipped, LOGIN_URL / ERP_EMAIL / ERP_PASSWORD not set; using models in DB")
        return False
    async with APICaller() as caller:
        login = await caller.call(
            "POST",
            f"{LOGIN_URL}/auth/login",
            json={"email": ERP_EMAIL, "password": ERP_PASSWORD, "remember_me": False},
            headers={"Accept": "application/json"},
            raise_for_status=False,
        )
    if login.is_error:
        logging.warning(f"seeder=model login failed {login.status_code}; using models already in DB")
        return False
    token = login.json()["data"]["access_token"]
    async with APICaller(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}) as caller:
        res = await caller.call("POST", "/models", raise_for_status=False)
    if res.is_error:
        logging.warning(f"seeder=model sync failed {res.status_code}: {res.text}; using models already in DB")
        return False
    return True


async def seed(force_sync: bool = False) -> None:
    async with make_session(DB_ASYNC_URL)() as db:
        has_models = (
            await query(
                db=db, table=DfEngineModelOptions, options=(load_only(DfEngineModelOptions.id),), fetch_one=True
            )
            is not None
        )
    if force_sync or not has_models:
        synced = await sync_models()
        if synced:
            async with make_session(DB_ASYNC_URL)() as db:
                if (
                    await query(
                        db=db, table=DfEngineModelOptions, options=(load_only(DfEngineModelOptions.id),), fetch_one=True
                    )
                    is None
                ):
                    logging.warning(
                        "seeder=model sync returned OK but df_engine_model_options is still empty, check OPENROUTER_API_KEY / df_engine_external_api_calls"
                    )
    else:
        logging.info("seeder=model sync skipped, models already in DB (use --sync to force)")
    enabled = 0
    async with make_session(DB_ASYNC_URL)() as db:
        default_text = None
        for model_type, needles in ENABLE.items():
            rows = await query(
                db=db,
                table=DfEngineModelOptions,
                filters=(
                    DfEngineModelOptions.type == model_type,
                    DfEngineModelOptions.deleted_at.is_(None),  # type: ignore
                    DfEngineModelOptions.is_available.is_(True),  # type: ignore
                ),
                order_by=(DfEngineModelOptions.name,),  # type: ignore
            )
            matched = [r for r in rows if any(n in f"{r.name} {r.model_id}".lower() for n in needles)]
            if not matched:
                logging.warning(f"seeder=model no {model_type.value} model matches {needles}, run model sync first")
            for row in matched:
                if not row.is_enabled:
                    row.is_enabled = True
                    enabled += 1
            if model_type == ModelUsageTypes.text:
                # enhancer/assistant must be an enabled, available text model; prefer a seeded match
                enabled_text = matched or [r for r in rows if r.is_enabled]
                default_text = enabled_text[0] if enabled_text else None

        if default_text:
            ref = json.dumps({"uid": default_text.uid, "name": default_text.name})
            for key in ("enhancer_model", "assistant_model"):
                row = await query(
                    db=db,
                    table=DfEngineSettings,
                    filters=(DfEngineSettings.code == SETTING_CODE, DfEngineSettings.key == key),
                    fetch_one=True,
                )
                if row is None:
                    db.add(DfEngineSettings(key=key, value=ref, code=SETTING_CODE))
                elif not row.value or json.loads(row.value) is None:
                    row.value, row.updated_at = ref, local_time()
        await db.commit()

    redis, keys = redis_client(), CacheKeys()
    for pattern in (
        keys.model_pagination_pattern(),
        keys.setting_global(),
        keys.setting_detail_pattern(),
        keys.setting_project_pattern(),
        keys.setting_logs_pattern(),
    ):
        await delete_pattern(redis, pattern)
    logging.info(f"seeder=model done, enabled={enabled} default_text={default_text.name if default_text else None}")


async def main() -> None:
    try:
        await seed(force_sync="--sync" in sys.argv)
    except Exception:
        logging.error(traceback.format_exc())
        raise
    finally:
        await engine(DB_ASYNC_URL).dispose()


if __name__ == "__main__":
    asyncio.run(main())
