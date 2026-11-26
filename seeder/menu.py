from sqlalchemy import delete, select, update
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
    DfEngineChatSessions,
    DfEngineGenerations,
)
from services.redis import client as redis_client, delete_pattern
from utils import local_time

FORMULAS = Path(__file__).resolve().parents[1] / "docs" / "formulas"
SEED = [
    (None, "initialize_session", "chat-session-init"),
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

MENU_ICONS = {
    "Gen": "mdi-creation",
    "Storyboard": "mdi-movie-open",
    "Elements": "mdi-shape",
}


async def prune(db, menu_names: set, template_names: set, feature_ids: set) -> dict:
    """Make SEED the only source of menus/features/templates: delete everything else together with its mappings.
    Features are matched by id, so an extra row sharing a seeded `type` is deleted too. A menu is only kept (deactivated)
    while a chat session sits in it. Generations survive but lose their menu/feature link (both columns are nullable)."""
    out = {"deleted": [], "deactivated": []}

    async def referenced(model_cols) -> bool:
        for col in model_cols:
            if (await db.execute(select(col).where(col == _id).limit(1))).first():
                return True
        return False

    async def drop(table, label, row, ref_cols=()):
        nonlocal _id
        _id = row.id
        if ref_cols and await referenced(ref_cols):
            if row.is_active:
                row.is_active = False
                db.add(row)
            out["deactivated"].append(f"{label}:{getattr(row, 'name')}")
        else:
            await db.delete(row)
            out["deleted"].append(f"{label}:{getattr(row, 'name')}")

    _id = None
    features = await query(db=db, table=DfEngineFeatures)
    for f in [f for f in features if f.id not in feature_ids]:
        await db.execute(delete(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.feature_id == f.id))
        await db.execute(delete(DfEngineFeaturePromptMappings).where(DfEngineFeaturePromptMappings.feature_id == f.id))
        await db.execute(
            update(DfEngineGenerations).where(DfEngineGenerations.feature_id == f.id).values(feature_id=None)
        )
        await drop(DfEngineFeatures, "feature", f)
    await db.flush()

    for m in [m for m in await query(db=db, table=DfEngineMenus) if m.name not in menu_names]:
        await db.execute(delete(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.menu_id == m.id))
        await db.execute(update(DfEngineGenerations).where(DfEngineGenerations.menu_id == m.id).values(menu_id=None))
        await drop(DfEngineMenus, "menu", m, (DfEngineChatSessions.menu_id,))
    await db.flush()

    for t in [t for t in await query(db=db, table=DfEnginePromptTemplates) if t.name not in template_names]:
        await db.execute(delete(DfEngineFeaturePromptMappings).where(DfEngineFeaturePromptMappings.template_id == t.id))
        await drop(DfEnginePromptTemplates, "template", t)
    return out


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

        menus, templates, feature_ids = {}, {}, set()
        for menu_name, ftype, tpl in SEED:
            if menu_name and menu_name not in menus:
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
                (DfEngineFeatures.name == ftype,),
                {"name": ftype, "type": ftype, "is_active": True},
            )
            feature_ids.add(feature.id)

            if menu_name:
                link = await query(
                    db=db,
                    table=DfEngineMenuFeatureMappings,
                    options=(load_only(DfEngineMenuFeatureMappings.id),),
                    filters=(DfEngineMenuFeatureMappings.feature_id == feature.id,),
                    fetch_one=True,
                )
                menu_link = await upsert(
                    DfEngineMenuFeatureMappings,
                    (DfEngineMenuFeatureMappings.id == link.id,) if link else (DfEngineMenuFeatureMappings.id == -1,),
                    {"feature_id": feature.id, "menu_id": menus[menu_name].id},
                )
            # A seeded feature keeps exactly the link SEED gives it (none for a menu-less one)
            await db.execute(
                delete(DfEngineMenuFeatureMappings).where(
                    DfEngineMenuFeatureMappings.feature_id == feature.id,
                    DfEngineMenuFeatureMappings.id != (menu_link.id if menu_name else -1),
                )
            )
            link = await query(
                db=db,
                table=DfEngineFeaturePromptMappings,
                options=(load_only(DfEngineFeaturePromptMappings.id),),
                filters=(DfEngineFeaturePromptMappings.feature_id == feature.id,),
                fetch_one=True,
            )
            prompt_link = await upsert(
                DfEngineFeaturePromptMappings,
                (DfEngineFeaturePromptMappings.id == link.id,) if link else (DfEngineFeaturePromptMappings.id == -1,),
                {"feature_id": feature.id, "template_id": templates[tpl].id},
            )
            await db.execute(
                delete(DfEngineFeaturePromptMappings).where(
                    DfEngineFeaturePromptMappings.feature_id == feature.id,
                    DfEngineFeaturePromptMappings.id != prompt_link.id,
                )
            )

        removed = await prune(db, set(menus), set(templates), feature_ids)
        await db.commit()

        redis = redis_client()
        for pattern in ("menu_management:*", "feature_management:*", "prompt_template:*", "menus:features:*"):
            await delete_pattern(redis, pattern)
        logging.info(f"seeder=menu done, created={stats['created']} updated={stats['updated']} {removed}")


async def main() -> None:
    try:
        await seed()
    except Exception:
        logging.error(traceback.format_exc())
        raise
    finally:
        await engine(DB_ASYNC_URL).dispose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
