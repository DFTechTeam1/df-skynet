from sqlalchemy.orm import load_only
import sys
import asyncio
import traceback
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from log import logging
from apps.secret import DB_ASYNC_URL
from services.mysql import engine, make_session, query
from services.mysql.model import (
    Users,
    DfEnginePromptTemplates,
    DfEngineFeatures,
    DfEngineMenus,
    DfEngineFeaturePromptMappings,
    DfEngineMenuFeatureMappings,
)
from services.redis import client as redis_client, delete_pattern
from utils import local_time

FORMULAS = Path(__file__).resolve().parents[1] / "docs" / "formulas"

SEED = [
    ("Gen", "generate_image", "image-led-fullgen"),
    ("Gen", "enhance_prompt", "image-led-fullgen"),
    ("Gen", "generate_video", "video-led-fullgen"),
    ("Storyboard", "generate_keyframe", "image-story-fullgen"),
    ("Storyboard", "generate_motion", "video-story-fullgen"),
    ("Elements", "generate_element_character", "image-asset-character"),
    ("Elements", "generate_element_object", "image-asset-object"),
    ("Elements", "generate_element_environment", "image-asset-environment"),
    ("Elements", "generate_element_style", "image-asset-style"),
]

# Vuetify (Material Design Icons) icon per menu
MENU_ICONS = {
    "Gen": "mdi-creation",
    "Storyboard": "mdi-movie-open",
    "Elements": "mdi-shape",
}


async def seed() -> None:
    async with make_session(DB_ASYNC_URL)() as db:
        user = await query(db=db, table=Users, options=(load_only(Users.id),), order_by=(Users.id,), fetch_one=True)  # type: ignore
        if not user:
            logging.error("seeder=menu aborted, users table is empty")
            return
        uid = user.id
        now = local_time()
        stats = {"created": 0, "updated": 0}

        async def upsert(table, filters, values):
            row = await query(db=db, table=table, filters=filters, fetch_one=True)
            if row is None:
                row = table(created_by=uid, **values) if hasattr(table, "created_by") else table(**values)
                db.add(row)
                await db.flush()
                stats["created"] += 1
            else:
                changed = {k: v for k, v in values.items() if getattr(row, k) != v}
                if changed:
                    for k, v in changed.items():
                        setattr(row, k, v)
                    if hasattr(row, "updated_by"):
                        row.updated_by, row.updated_at = uid, now
                    stats["updated"] += 1
            return row

        menus, templates = {}, {}
        for menu_name, ftype, tpl in SEED:
            if menu_name not in menus:
                menus[menu_name] = await upsert(
                    DfEngineMenus,
                    (DfEngineMenus.name == menu_name,),
                    {"name": menu_name, "icon": MENU_ICONS[menu_name], "is_active": True},
                )
            if tpl not in templates:
                templates[tpl] = await upsert(
                    DfEnginePromptTemplates,
                    (DfEnginePromptTemplates.name == tpl,),
                    {"name": tpl, "prompt": (FORMULAS / f"{tpl}.md").read_text(encoding="utf-8"), "is_active": True},
                )

            feature = await upsert(
                DfEngineFeatures,
                (DfEngineFeatures.type == ftype,),
                {"name": ftype, "type": ftype, "is_active": True},
            )

            link = await query(
                db=db,
                table=DfEngineMenuFeatureMappings,
                options=(load_only(DfEngineMenuFeatureMappings.id),),
                filters=(DfEngineMenuFeatureMappings.feature_id == feature.id,),
                fetch_one=True,
            )
            await upsert(
                DfEngineMenuFeatureMappings,
                (DfEngineMenuFeatureMappings.id == link.id,) if link else (DfEngineMenuFeatureMappings.id == -1,),
                {"feature_id": feature.id, "menu_id": menus[menu_name].id},
            )
            link = await query(
                db=db,
                table=DfEngineFeaturePromptMappings,
                options=(load_only(DfEngineFeaturePromptMappings.id),),
                filters=(DfEngineFeaturePromptMappings.feature_id == feature.id,),
                fetch_one=True,
            )
            await upsert(
                DfEngineFeaturePromptMappings,
                (DfEngineFeaturePromptMappings.id == link.id,) if link else (DfEngineFeaturePromptMappings.id == -1,),
                {"feature_id": feature.id, "template_id": templates[tpl].id},
            )

        await db.commit()

        redis = redis_client()
        for pattern in ("menu_management:*", "feature_management:*", "prompt_template:*", "menus:features:*"):
            await delete_pattern(redis, pattern)
        logging.info(f"seeder=menu done, created={stats['created']} updated={stats['updated']}")


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
