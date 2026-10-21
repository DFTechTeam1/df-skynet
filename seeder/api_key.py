import sys
import time
import asyncio
import traceback
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func
from log import logging
from apps.secret import DB_ASYNC_URL, OPENROUTER_BASE_URL, OPENROUTER_MANAGEMENT_KEY
from services.api_caller import APICaller
from services.mysql import engine, make_session, query
from services.mysql.model import DfEngineApiKeys, DfEngineExternalApiCalls, Employees, PositionBackups, Users
from services.redis import client as redis_client, delete_pattern, CacheKeys

PIC_POSITIONS = ["project manager", "assistant project manager"]


async def seed() -> None:
    if not OPENROUTER_MANAGEMENT_KEY or not OPENROUTER_BASE_URL:
        logging.error("seeder=api_key aborted, OPENROUTER_MANAGEMENT_KEY / OPENROUTER_BASE_URL not set")
        return

    async with make_session(DB_ASYNC_URL)() as db:
        user = await query(db=db, table=Users, order_by=(Users.id,), fetch_one=True)  # type: ignore
        if not user:
            logging.error("seeder=api_key aborted, users table is empty")
            return

        employees = await query(
            db=db,
            table=Employees,
            columns=(Employees.id, Employees.nickname),
            joins=((PositionBackups, Employees.position_id == PositionBackups.id),),
            filters=(
                func.lower(func.trim(PositionBackups.name)).in_(PIC_POSITIONS),
                Employees.deleted_at.is_(None),  # type: ignore
                Employees.user_id.isnot(None),  # type: ignore
            ),
        )
        header = {"Authorization": f"Bearer {OPENROUTER_MANAGEMENT_KEY}"}
        created = skipped = failed = 0

        for emp in employees:
            has_main = await query(
                db=db,
                table=DfEngineApiKeys,
                columns=(DfEngineApiKeys.id,),
                filters=(
                    DfEngineApiKeys.employee_id == emp.id,
                    DfEngineApiKeys.is_main.is_(True),  # type: ignore
                    DfEngineApiKeys.created_by.isnot(None),  # type: ignore
                    DfEngineApiKeys.hash.isnot(None),  # type: ignore
                ),
                fetch_one=True,
            )
            if has_main is not None:
                skipped += 1
                continue

            name = f"{emp.nickname} · Main"
            payload = {
                "expires_at": None,
                "include_byok_in_limit": True,
                "limit": None,
                "limit_reset": None,
                "name": name,
            }
            started_at = time.perf_counter()
            async with APICaller(base_url=OPENROUTER_BASE_URL, headers=header) as caller:
                res = await caller.call("POST", "/keys", raise_for_status=False, json=payload)
            body = res.json() if res.content else {}
            error = f"openrouter {res.status_code}: {body or res.text}" if res.is_error else None

            if not error:
                db.add(
                    DfEngineApiKeys(
                        name=name,
                        key=body["key"],
                        hash=body["data"]["hash"],
                        employee_id=emp.id,
                        employee_name=emp.nickname,
                        is_main=True,
                        created_by=user.id,
                    )
                )
            db.add(
                DfEngineExternalApiCalls(
                    name=emp.nickname,
                    type="openrouter",
                    method="POST",
                    endpoint=str(res.request.url),
                    request_headers={**header, "Authorization": "Bearer ***"},
                    request_payload=payload,
                    response_status_code=res.status_code,
                    response_headers=dict(res.headers),
                    response_body=body or None,
                    error_message=error,
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
            )
            await db.flush()
            if error:
                failed += 1
                logging.error(f"seeder=api_key could not create key for employee={emp.id}: {error}")
            else:
                created += 1

        await db.commit()

    await delete_pattern(redis_client(), CacheKeys().api_key_management_pattern())
    logging.info(f"seeder=api_key done, created={created} skipped={skipped} failed={failed}")


async def main() -> None:
    try:
        await seed()
    except Exception:
        logging.error(traceback.format_exc())
        raise
    finally:
        await engine(DB_ASYNC_URL).dispose()


if __name__ == "__main__":
    asyncio.run(main())
