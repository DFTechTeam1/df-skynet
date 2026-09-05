"""Manual smoke test for the two polymorphic attributes on
`df_engine_prompt_enhancers` — `sourceable` and `featureable` — exercised
through a full create/fetch/update/delete cycle, each step's result printed
as JSON.

`model_id`/`project_id`/`task_id` are plain (non-polymorphic) FKs. The two
polymorphic pairs:
  - `sourceable_id`/`sourceable_type`   -> df_engine_api_keys or df_engine_api_key_snapshots
  - `featureable_id`/`featureable_type` -> df_engine_features or df_engine_feature_snapshots

The feature-snapshot row also carries a real (non-polymorphic) one-to-many
`df_engine_prompt_template_snapshots` list, eagerly loaded via
`Session.get(options=...)` inside `featureable` — proving that a resolved
polymorphic row can itself carry normally-loaded nested relations that
`serialize()` picks up.

Run: python example/sample_poly.py
"""

import sys
import asyncio
from pathlib import Path
import json

sys.path.append(str(Path(__file__).resolve().parents[1]))

from apps.secret import DB_ASYNC_URL, DB_SYNC_URL
from services.mysql import engine, make_session, make_sync_session, query
from services.mysql.factory.df_engine_api_key_snapshots import DfEngineApiKeySnapshotsFactory
from services.mysql.factory.df_engine_api_keys import DfEngineApiKeysFactory
from services.mysql.factory.df_engine_feature_snapshots import DfEngineFeatureSnapshotsFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_prompt_enhancers import DfEnginePromptEnhancersFactory
from services.mysql.factory.df_engine_prompt_template_snapshots import DfEnginePromptTemplateSnapshotsFactory
from services.mysql.model import (
    DfEngineApiKeys,
    DfEngineApiKeySnapshots,
    DfEngineFeatures,
    DfEngineFeatureSnapshots,
    DfEngineModelOptions,
    DfEnginePromptEnhancers,
    ProjectTasks,
    Projects,
    Users,
)
from utils.serializer import serialize


def print_json(label: str, data) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2))


def create() -> list[int]:
    session = make_sync_session(DB_SYNC_URL)
    user = session.query(Users).first()
    project = session.query(Projects).first()
    task = session.query(ProjectTasks).first()
    assert user and project and task, "dev DB is missing a users/projects/project_tasks row to seed sample_poly against"

    # These tables are owned by this migration chain, so a fresh/just-migrated
    # DB has none of them yet — fall back to creating one via the factory.
    model_option = session.query(DfEngineModelOptions).first() or DfEngineModelOptionsFactory.create()
    feature = session.query(DfEngineFeatures).first() or DfEngineFeaturesFactory.create(created_by=user.id)
    api_key = session.query(DfEngineApiKeys).first() or DfEngineApiKeysFactory.create(created_by=user.id)
    api_key_snapshot = session.query(DfEngineApiKeySnapshots).first() or DfEngineApiKeySnapshotsFactory.create(
        created_by=user.id
    )

    feature_snapshot = session.query(DfEngineFeatureSnapshots).first()
    if feature_snapshot is None:
        feature_snapshot = DfEngineFeatureSnapshotsFactory.create(created_by=user.id)
        # The "list of values" — a few prompt template snapshots hanging off
        # this one feature snapshot, so `featureable` has something to show.
        for title in ("Upscale pass", "Rim-lighting pass", "Color-grade pass"):
            DfEnginePromptTemplateSnapshotsFactory.create(
                feature_snapshot_id=feature_snapshot.id, name=title, created_by=user.id
            )

    live_enhancer = DfEnginePromptEnhancersFactory.create(
        model_id=model_option.id,
        project_id=project.id,
        task_id=task.id,
        created_by=user.id,
        raw="upscale this render",
        sourceable_id=api_key.id,
        sourceable_type=type(api_key).__name__,
        featureable_id=feature.id,
        featureable_type=type(feature).__name__,
    )
    archived_enhancer = DfEnginePromptEnhancersFactory.create(
        model_id=model_option.id,
        project_id=project.id,
        task_id=task.id,
        created_by=user.id,
        raw="add rim lighting",
        sourceable_id=api_key_snapshot.id,
        sourceable_type=type(api_key_snapshot).__name__,
        featureable_id=feature_snapshot.id,
        featureable_type=type(feature_snapshot).__name__,
    )
    # Created via the sync session (factories), so `.sourceable`/`.featureable`
    # can resolve immediately here — no run_sync needed outside of async code.
    print_json("CREATE", serialize([live_enhancer, archived_enhancer]))
    return [live_enhancer.id, archived_enhancer.id]


async def fetch(db, enhancer_ids: list[int], label: str) -> list[DfEnginePromptEnhancers]:
    rows = await query(
        db=db,
        table=DfEnginePromptEnhancers,
        filters=(DfEnginePromptEnhancers.id.in_(enhancer_ids),),  # type: ignore
    )
    # `.sourceable`/`.featureable` resolve via the row's bound sync Session, so
    # `serialize()` (which touches them) has to run inside run_sync's greenlet.
    print_json(label, await db.run_sync(lambda _: serialize(rows)))
    return rows


async def update(db, enhancer_id: int) -> None:
    rows = await query(db=db, table=DfEnginePromptEnhancers, filters=(DfEnginePromptEnhancers.id == enhancer_id,))
    row = rows[0]
    row.enhanced = "upscaled to 4K, added a rim-lighting pass"
    row.status_code = 201
    row.is_processing = False
    db.add(row)
    await db.commit()
    await db.refresh(row)
    print_json("UPDATE", await db.run_sync(lambda _: serialize(row)))


async def delete(db, enhancer_id: int) -> None:
    rows = await query(db=db, table=DfEnginePromptEnhancers, filters=(DfEnginePromptEnhancers.id == enhancer_id,))
    await db.delete(rows[0])
    await db.commit()
    print_json("DELETE", {"deleted_id": enhancer_id})


async def main(enhancer_ids: list[int]) -> None:
    live_id, archived_id = enhancer_ids
    async with make_session(DB_ASYNC_URL)() as db:
        await fetch(db, enhancer_ids, "FETCH")
        # await update(db, live_id)
        # await delete(db, archived_id)
        await fetch(db, enhancer_ids, "FETCH AFTER UPDATE/DELETE")

    await engine(DB_ASYNC_URL).dispose()


if __name__ == "__main__":
    asyncio.run(main(create()))
