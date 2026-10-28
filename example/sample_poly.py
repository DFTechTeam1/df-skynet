"""Sample CRUD walk-through for the polymorphic `sourceable` on
`df_engine_generations`, run end to end and printed as JSON at every step.

`df_engine_generations.sourceable_id` / `sourceable_type` is a manual
polymorphic ("morph") reference: the row points at EITHER a
`df_engine_api_keys` row OR a `df_engine_api_key_snapshots` row. It's modeled
as two `viewonly` relationships (`api_key`, `api_key_snapshot`) whose own
primaryjoin bakes in the `sourceable_type` discriminator, so only the
matching one ever loads - `services/mysql/model/df_engine_generations.py`.
Being real relationships, they're eager-loaded via plain `selectinload()` and
picked up by `serialize()`'s normal relationship walk like any other FK, with
no manual session lookups and no greenlet gymnastics required under
`AsyncSession`. `model_id`, `menu_id`, `feature_id`, `project_id`, `task_id`
are ordinary (non-polymorphic) FKs, shown for contrast.

Run: python example/sample_poly.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import selectinload
from apps.secret import DB_ASYNC_URL, DB_SYNC_URL
from services.mysql import engine, make_session, make_sync_session, query
from services.mysql.factory.df_engine_api_key_snapshots import DfEngineApiKeySnapshotsFactory
from services.mysql.factory.df_engine_api_keys import DfEngineApiKeysFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.model import (
    DfEngineApiKeys,
    DfEngineApiKeySnapshots,
    DfEngineFeatures,
    DfEngineGenerations,
    DfEngineMenus,
    DfEngineModelOptions,
    Users,
)
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from utils.serializer import serialize

SOURCEABLE_LOADERS = (selectinload(DfEngineGenerations.api_key), selectinload(DfEngineGenerations.api_key_snapshot))


def print_json(label: str, data) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str))


# --------------------------------------------------------------------------- #
# CREATE                                                                      #
# --------------------------------------------------------------------------- #
def create() -> list[int]:
    """Insert two generations that differ ONLY in what `sourceable` points at:
    one at a live `df_engine_api_keys` row, one at an archived
    `df_engine_api_key_snapshots` row. Returns their ids."""
    session = make_sync_session(DB_SYNC_URL)

    user = session.query(Users).first()
    assert user is not None, "dev DB has no users row to satisfy created_by / menu.created_by"

    # Non-polymorphic FK targets — reuse whatever's already there, else seed one.
    model_option = session.query(DfEngineModelOptions).first() or DfEngineModelOptionsFactory.create()
    menu = session.query(DfEngineMenus).first() or DfEngineMenusFactory.create(
        created_by=user.id, df_engine_menu_feature_mapping=None
    )
    feature = session.query(DfEngineFeatures).first() or DfEngineFeaturesFactory.create(
        created_by=user.id, df_engine_feature_prompt_mapping=None
    )

    # The two polymorphic targets.
    api_key = session.query(DfEngineApiKeys).first() or DfEngineApiKeysFactory.create(created_by=user.id)
    api_key_snapshot = session.query(DfEngineApiKeySnapshots).first() or DfEngineApiKeySnapshotsFactory.create(
        created_by=user.id
    )

    common = dict(
        model_id=model_option.id,
        menu_id=menu.id,
        feature_id=feature.id,
        created_by=user.id,
    )

    # sourceable_type is the class NAME — `type(obj).__name__` — matching the discriminator
    # each of `DfEngineGenerations.api_key` / `api_key_snapshot`'s primaryjoin compares against.
    live = DfEngineGenerationsFactory.create(
        kind=GenerationKinds.image,
        prompt="a neon-lit alley at night, rain-slicked cobblestones",
        sourceable_id=api_key.id,
        sourceable_type=type(api_key).__name__,
        **common,
    )
    archived = DfEngineGenerationsFactory.create(
        kind=GenerationKinds.video,
        prompt="slow push-in on a coffee cup, morning light",
        sourceable_id=api_key_snapshot.id,
        sourceable_type=type(api_key_snapshot).__name__,
        **common,
    )
    session.close()
    return [live.id, archived.id]


# --------------------------------------------------------------------------- #
# READ                                                                        #
# --------------------------------------------------------------------------- #
async def fetch(db, generation_ids: list[int], label: str) -> list[DfEngineGenerations]:
    rows = await query(
        db=db,
        table=DfEngineGenerations,
        options=SOURCEABLE_LOADERS,
        filters=(DfEngineGenerations.id.in_(generation_ids),),  # type: ignore
        order_by=(DfEngineGenerations.id.asc(),),  # type: ignore
    )
    # api_key/api_key_snapshot are real, eager-loaded relationships now - plain serialize(),
    # no run_sync needed.
    print_json(label, serialize(rows))
    return rows


# --------------------------------------------------------------------------- #
# UPDATE                                                                      #
# --------------------------------------------------------------------------- #
async def update(db, generation_id: int) -> None:
    row = await query(
        db=db,
        table=DfEngineGenerations,
        options=SOURCEABLE_LOADERS,
        filters=(DfEngineGenerations.id == generation_id,),  # type: ignore
        fetch_one=True,
    )
    row.status = GenerationStatuses.success
    row.status_code = 200
    row.token_usage = 1280
    row.cost = 0.42
    row.response = {"url": "https://cdn.example/out/neon-alley.png"}
    db.add(row)
    await db.commit()
    await db.refresh(row)
    print_json("UPDATE", serialize(row))


# --------------------------------------------------------------------------- #
# DELETE                                                                      #
# --------------------------------------------------------------------------- #
async def delete(db, generation_id: int) -> None:
    row = await query(
        db=db,
        table=DfEngineGenerations,
        filters=(DfEngineGenerations.id == generation_id,),  # type: ignore
        fetch_one=True,
    )
    await db.delete(row)
    await db.commit()
    print_json("DELETE", {"deleted_id": generation_id})


# --------------------------------------------------------------------------- #
async def main(generation_ids: list[int]) -> None:
    live_id, archived_id = generation_ids
    async with make_session(DB_ASYNC_URL)() as db:
        await fetch(db, generation_ids, "FETCH (both, sourceable resolved to different tables)")
        await update(db, live_id)
        await delete(db, archived_id)
        await fetch(db, generation_ids, "FETCH AFTER UPDATE + DELETE")

    await engine(DB_ASYNC_URL).dispose()


if __name__ == "__main__":
    asyncio.run(main(create()))
