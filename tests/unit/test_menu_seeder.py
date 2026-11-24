"""The menu seeder against an in-memory stand-in for the DB (the real seeder prunes everything not in SEED, so it must
never run against the shared test database)."""

from types import SimpleNamespace
import pytest
from seeder import menu as seeder
from services.mysql.model import (
    DfEngineFeaturePromptMappings,
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    DfEnginePromptTemplates,
    Users,
)


class FakeDb:
    def __init__(self, referenced=False):
        self.store = {}
        self.next_id = 0
        self.referenced = referenced
        self.deleted_statements = 0
        self.unlinked_generations = 0

    def rows(self, table):
        return self.store.setdefault(table, [])

    def add(self, row):
        self.next_id += 1
        row.id = self.next_id
        self.rows(type(row)).append(row)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def delete(self, row):
        self.rows(type(row)).remove(row)

    async def execute(self, statement):
        if "DELETE" in str(statement):
            self.deleted_statements += 1
        if "UPDATE df_engine_generations" in str(statement):
            self.unlinked_generations += 1
        return SimpleNamespace(first=lambda: ("hit",) if self.referenced else None)

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def fake(monkeypatch):
    db = FakeDb()
    db.rows(Users).append(SimpleNamespace(id=1))

    async def query(db, table, filters=(), fetch_one=False, **kwargs):
        rows = [r for r in db.rows(table) if all(getattr(r, f.left.key) == f.right.value for f in filters)]
        return (rows[0] if rows else None) if fetch_one else rows

    async def delete_pattern(redis, pattern):
        db.patterns.append(pattern)

    db.patterns = []
    monkeypatch.setattr(seeder, "make_session", lambda url: db)
    monkeypatch.setattr(seeder, "query", query)
    monkeypatch.setattr(seeder, "redis_client", lambda: None)
    monkeypatch.setattr(seeder, "delete_pattern", delete_pattern)
    return db


def test_every_seed_row_has_a_formula_file_and_only_initialize_session_has_no_menu():
    assert all((seeder.FORMULAS / f"{tpl}.md").is_file() for _, _, tpl in seeder.SEED)
    assert [ftype for menu, ftype, _ in seeder.SEED if menu is None] == ["initialize_session"]
    assert {menu for menu, _, _ in seeder.SEED if menu} <= set(seeder.MENU_ICONS)


@pytest.mark.asyncio
async def test_initialize_session_is_seeded_without_a_menu_and_a_second_run_changes_nothing(fake):
    await seeder.seed()
    features = {f.type: f for f in fake.rows(DfEngineFeatures)}
    assert set(features) == {ftype for _, ftype, _ in seeder.SEED}
    mapped = {m.feature_id for m in fake.rows(DfEngineMenuFeatureMappings)}
    assert features["initialize_session"].id not in mapped and len(mapped) == len(seeder.SEED) - 1
    assert len(fake.rows(DfEngineFeaturePromptMappings)) == len(seeder.SEED)
    assert {m.name for m in fake.rows(DfEngineMenus)} == set(seeder.MENU_ICONS)
    assert "chat-session-init" in {t.name for t in fake.rows(DfEnginePromptTemplates)}
    assert "menus:features:*" in fake.patterns

    snapshot = {t: [dict(vars(r)) for r in rows] for t, rows in fake.store.items()}
    await seeder.seed()
    assert {t: [dict(vars(r)) for r in rows] for t, rows in fake.store.items()} == snapshot


@pytest.mark.asyncio
async def test_seed_updates_a_changed_row_and_prunes_what_is_not_seeded(fake):
    await seeder.seed()
    template = fake.rows(DfEnginePromptTemplates)[0]
    template.prompt = "stale"
    stale = DfEngineFeatures(name="old", type="old", is_active=True)
    fake.add(stale)
    await seeder.seed()
    assert template.prompt != "stale" and stale not in fake.rows(DfEngineFeatures)
    assert fake.deleted_statements


@pytest.mark.asyncio
async def test_a_stale_row_that_history_still_uses_is_deactivated_not_deleted(fake):
    await seeder.seed()
    fake.referenced = True
    stale = DfEngineFeatures(name="old", type="old", is_active=True)
    stale_menu = DfEngineMenus(name="Old", icon="x", is_active=False)
    fake.add(stale)
    fake.add(stale_menu)
    await seeder.seed()
    assert stale in fake.rows(DfEngineFeatures) and stale.is_active is False
    assert stale_menu in fake.rows(DfEngineMenus)  # a chat session still sits in it


@pytest.mark.asyncio
async def test_a_stale_menu_is_deleted_and_its_generations_lose_only_the_menu_link(fake):
    await seeder.seed()
    stale_menu = DfEngineMenus(name="Menu abc", icon=None, is_active=True)
    fake.add(stale_menu)
    await seeder.seed()
    assert stale_menu not in fake.rows(DfEngineMenus)
    assert fake.unlinked_generations == 1  # only the stale menu is unlinked, the seeded ones are never pruned


@pytest.mark.asyncio
async def test_seed_aborts_when_there_is_no_user(fake):
    fake.rows(Users).clear()
    await seeder.seed()
    assert not fake.rows(DfEngineFeatures)


@pytest.mark.asyncio
async def test_main_logs_and_reraises_a_seed_failure_and_always_disposes(monkeypatch):
    disposed = []

    class Engine:
        async def dispose(self):
            disposed.append(True)

    async def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(seeder, "engine", lambda url: Engine())
    monkeypatch.setattr(seeder, "seed", boom)
    with pytest.raises(RuntimeError):
        await seeder.main()
    monkeypatch.setattr(seeder, "seed", lambda: _noop())
    await seeder.main()
    assert disposed == [True, True]


async def _noop():
    return None


@pytest.mark.asyncio
async def test_a_stale_template_and_a_moved_link_are_fixed_on_the_next_run(fake):
    await seeder.seed()
    link = fake.rows(DfEngineMenuFeatureMappings)[0]
    right_menu = link.menu_id
    link.menu_id = -1
    stale = DfEnginePromptTemplates(name="old-template", prompt="x", is_active=True)
    fake.add(stale)
    await seeder.seed()
    assert link.menu_id == right_menu and stale not in fake.rows(DfEnginePromptTemplates)
