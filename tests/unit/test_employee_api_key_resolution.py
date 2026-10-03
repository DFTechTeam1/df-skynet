import pytest
from unittest.mock import AsyncMock
import services.dto.asynced.api_keys as api_keys
from error import DataNotFoundError


def _ctx():
    return type("Ctx", (), {"db": object()})()


@pytest.mark.asyncio
async def test_uses_own_key_when_employee_is_project_pic(monkeypatch):
    monkeypatch.setattr(api_keys, "get_project_pics", AsyncMock(return_value=[{"pic_id": 7}]))
    get_api_key = AsyncMock(return_value={"id": 7, "key": "own-key"})
    monkeypatch.setattr(api_keys, "get_api_key", get_api_key)

    result = await api_keys.get_employee_api_key(None, project_id=300, employee_user={"id": 7, "boss_id": 5})

    get_api_key.assert_awaited_once_with(None, 7)
    assert result == {"id": 7, "key": "own-key"}


@pytest.mark.asyncio
async def test_uses_boss_key_when_boss_is_project_pic(monkeypatch):
    """Employee isn't a direct PIC and has no approved transfer, but their boss is a direct PIC."""
    ctx = _ctx()
    monkeypatch.setattr(api_keys, "get_project_pics", AsyncMock(return_value=[{"pic_id": 5}, {"pic_id": 1}]))
    monkeypatch.setattr(api_keys, "query", AsyncMock(return_value=None))
    get_api_key = AsyncMock(return_value={"id": 5, "key": "boss-key"})
    monkeypatch.setattr(api_keys, "get_api_key", get_api_key)

    result = await api_keys.get_employee_api_key(ctx, project_id=300, employee_user={"id": 7, "boss_id": 5})

    get_api_key.assert_awaited_once_with(ctx, 5, raise_if_missing=False)
    assert result == {"id": 5, "key": "boss-key"}


@pytest.mark.asyncio
async def test_uses_requested_by_key_when_approved_transfer_matches(monkeypatch):
    """Neither employee nor boss is a direct PIC, but an approved transfer brought the staff onto this project."""
    ctx = _ctx()
    monkeypatch.setattr(api_keys, "get_project_pics", AsyncMock(return_value=[]))
    fake_transfer_row = type("Row", (), {"requested_by": 42})()
    monkeypatch.setattr(api_keys, "query", AsyncMock(return_value=fake_transfer_row))
    get_api_key = AsyncMock(return_value={"id": 42, "key": "transfer-key"})
    monkeypatch.setattr(api_keys, "get_api_key", get_api_key)

    result = await api_keys.get_employee_api_key(ctx, project_id=300, employee_user={"id": 7, "boss_id": 5})

    get_api_key.assert_awaited_once_with(ctx, 42, raise_if_missing=False)
    assert result == {"id": 42, "key": "transfer-key"}


@pytest.mark.asyncio
async def test_transfer_falls_back_to_lead_pic_when_requested_by_has_no_key(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(
        api_keys, "get_project_pics", AsyncMock(return_value=[{"pic_id": 9, "is_lead": True}, {"pic_id": 1}])
    )
    fake_transfer_row = type("Row", (), {"requested_by": 42})()
    monkeypatch.setattr(api_keys, "query", AsyncMock(return_value=fake_transfer_row))

    async def fake_get_api_key(ctx, employee_id, raise_if_missing=True):
        return {"id": 9, "key": "lead-key"} if employee_id == 9 else None

    monkeypatch.setattr(api_keys, "get_api_key", fake_get_api_key)

    result = await api_keys.get_employee_api_key(ctx, project_id=300, employee_user={"id": 7, "boss_id": 5})

    assert result == {"id": 9, "key": "lead-key"}


@pytest.mark.asyncio
async def test_boss_falls_back_to_lead_pic_when_boss_is_not_a_pic(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(api_keys, "get_project_pics", AsyncMock(return_value=[{"pic_id": 9, "is_lead": True}]))
    monkeypatch.setattr(api_keys, "query", AsyncMock(return_value=None))
    get_api_key = AsyncMock(return_value={"id": 9, "key": "lead-key"})
    monkeypatch.setattr(api_keys, "get_api_key", get_api_key)

    result = await api_keys.get_employee_api_key(ctx, project_id=300, employee_user={"id": 7, "boss_id": 5})

    get_api_key.assert_awaited_once_with(ctx, 9, raise_if_missing=False)
    assert result == {"id": 9, "key": "lead-key"}


@pytest.mark.asyncio
async def test_raises_when_nothing_resolves(monkeypatch):
    """No self-PIC, no transfer, boss isn't a PIC, and there's no lead PIC either."""
    ctx = _ctx()
    monkeypatch.setattr(api_keys, "get_project_pics", AsyncMock(return_value=[]))
    monkeypatch.setattr(api_keys, "query", AsyncMock(return_value=None))
    get_api_key = AsyncMock(return_value=None)
    monkeypatch.setattr(api_keys, "get_api_key", get_api_key)

    with pytest.raises(DataNotFoundError):
        await api_keys.get_employee_api_key(ctx, project_id=300, employee_user={"id": 7, "boss_id": None})
