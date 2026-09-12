import sys
import json
import asyncio
import traceback
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from log import logging
from apps.secret import DB_ASYNC_URL
from services.mysql import engine, make_session, query
from services.mysql.model import DfEngineSettings
from services.mysql.factory import DfEngineSettingsFactory

SETTING_CODE = "menu_management"
KEY = "menu_management_options"
VALUES = ["generations", "storyboards", "assistants", "files", "elements"]


async def seed() -> None:
    async with make_session(DB_ASYNC_URL)() as db:
        existing = await query(db=db, table=DfEngineSettings, filters=(DfEngineSettings.code == SETTING_CODE,))
        if existing:
            logging.info(f"seeder={SETTING_CODE} skipped, {len(existing)} row(s) already present")
            return

    DfEngineSettingsFactory.create(key=KEY, value=json.dumps(VALUES), code=SETTING_CODE)
    logging.info(f"seeder={SETTING_CODE} inserted 1 row")


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
