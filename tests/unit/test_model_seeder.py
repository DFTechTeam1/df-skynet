from types import SimpleNamespace
import httpx
import pytest
from seeder import model as seeder
from seeder.model import ASSISTANT_MODELS, pick_assistant_models


def _rows(*names):
    return [SimpleNamespace(name=name) for name in names]


def test_assistant_models_are_picked_in_preference_order_by_exact_name():
    first, second, third = ASSISTANT_MODELS
    assert [r.name for r in pick_assistant_models(_rows(third, second, first))] == ASSISTANT_MODELS
    assert pick_assistant_models(_rows(third, f"{second} (batch)", second))[0].name == second
    assert pick_assistant_models(_rows(third))[0].name == third
    assert pick_assistant_models(_rows(f"{first} (batch)", "Google: Gemini 2.5 Flash")) == []


@pytest.mark.asyncio
async def test_an_unreachable_api_does_not_stop_the_seeder(monkeypatch):
    """The sync raising a connection error must fall through to seeding from the models already in the DB."""

    class Reached(Exception):
        pass

    sessions = []

    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    async def sync_models():
        raise httpx.ConnectError("name resolution")

    async def query(**kwargs):
        if sessions:
            raise Reached  # got past the sync, into the enabling step
        return None

    monkeypatch.setattr(seeder, "sync_models", sync_models)
    monkeypatch.setattr(seeder, "query", query)
    monkeypatch.setattr(seeder, "make_session", lambda url: Db)
    monkeypatch.setattr(seeder.logging, "warning", lambda message: sessions.append(message))
    with pytest.raises(Reached):
        await seeder.seed(force_sync=True)
    assert "sync failed" in sessions[0]
