"""Sample CRUD walk-through for the polymorphic `sourceable` on
`df_engine_generations`, run end to end and printed as JSON at every step.

`df_engine_generations.sourceable_id` / `sourceable_type` is a manual
polymorphic ("morph") reference: the row points at EITHER a
`df_engine_api_keys` row OR a `df_engine_api_key_snapshots` row, and the
model resolves it through the `sourceable` cached_property
(`services/mysql/model/df_engine_generations.py`). `model_id`, `menu_id`,
`feature_id`, `project_id`, `task_id` are ordinary (non-polymorphic) FKs.

How the two DB sessions are used:
  - CREATE goes through the factories, which run on a plain *sync* Session
    (`make_sync_session`). `.sourceable` reads via `object_session(self)`, so
    right after a factory create it resolves immediately and `serialize()`
    can touch it directly.
  - READ / UPDATE / DELETE use an *async* Session. `.sourceable` still needs
    the row's bound sync greenlet, so `serialize()` (which walks
    cached_property) has to run inside `AsyncSession.run_sync(...)`.

Run: python example/sample_poly.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

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

    # sourceable_type is the class NAME — `type(obj).__name__` — matching what
    # `DfEngineGenerations.is_api_key` / `is_api_key_snapshot` compare against.
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

    # Sync session -> `.sourceable` resolves right now, `serialize()` picks it
    # up because it walks cached_property attributes on the MRO.
    print_json("CREATE", serialize([live, archived]))
    return [live.id, archived.id]


# --------------------------------------------------------------------------- #
# READ                                                                        #
# --------------------------------------------------------------------------- #
async def fetch(db, generation_ids: list[int], label: str) -> list[DfEngineGenerations]:
    rows = await query(
        db=db,
        table=DfEngineGenerations,
        filters=(DfEngineGenerations.id.in_(generation_ids),),  # type: ignore
        order_by=(DfEngineGenerations.id.asc(),),  # type: ignore
    )
    # `.sourceable` resolves via each row's bound sync Session, so serialize()
    # must run inside run_sync's greenlet.
    print_json(label, await db.run_sync(lambda _: serialize(rows)))
    return rows


# --------------------------------------------------------------------------- #
# UPDATE                                                                      #
# --------------------------------------------------------------------------- #
async def update(db, generation_id: int) -> None:
    row = await query(
        db=db,
        table=DfEngineGenerations,
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
    print_json("UPDATE", await db.run_sync(lambda _: serialize(row)))


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
