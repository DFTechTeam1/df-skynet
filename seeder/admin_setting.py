import sys
import json
import asyncio
import traceback
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from log import logging
from apps.secret import DB_ASYNC_URL
from services.mysql import engine, make_session, query
from services.mysql.model import ProjectClasses, DfEngineSettings
from services.mysql.factory import DfEngineSettingsFactory

SETTING_CODE = "admin_setting"


def project_class_config(project_classes: list[ProjectClasses]) -> list[dict]:
    return [
        {
            "id": pc.id,
            "name": pc.name,
            "color": pc.color,
            "token_usage_limit": 1,
            "concurent_generations": 1,
            "compose_input_max_chars": 2000,
            "storyboard_prompt_chars": 2000,
            "max_scene_per_storyboard": 10,
            "max_shot_per_scene": 100,
        }
        for pc in project_classes
    ]


async def seed() -> None:
    async with make_session(DB_ASYNC_URL)() as db:
        existing = await query(db=db, table=DfEngineSettings, filters=(DfEngineSettings.code == SETTING_CODE,))
        if existing:
            logging.info(f"seeder={SETTING_CODE} skipped, {len(existing)} row(s) already present")
            return

        project_classes = await query(db=db, table=ProjectClasses)
        if not project_classes:
            logging.error(f"seeder={SETTING_CODE} aborted, project_classes table is empty")
            return

    settings = {
        "admin_view": {"see_all_asset": True},
        "project_class_limitations": project_class_config(project_classes),
        "enhancer_model": None,
        "assistant_model": None,
        "threshold_token_usage_limit": 0.8,
    }
    for key, value in settings.items():
        DfEngineSettingsFactory.create(key=key, value=json.dumps(value), code=SETTING_CODE)

    logging.info(f"seeder={SETTING_CODE} inserted {len(settings)} row(s) for {len(project_classes)} project class")


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
