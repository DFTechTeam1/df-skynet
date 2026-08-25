import pytest
import pytest_asyncio
from typing import Any
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineModelOptions
from tests.helpers import create_record

URL = "/api/models"


@pytest_asyncio.fixture(autouse=True)
async def _restore_real_main_state(db_session):
    """These tests promote fixtures to main alongside any REAL, already-synced
    row. Snapshot every row that's main before the test and force that exact
    set back afterward, so these tests can never permanently alter real
    production main-model state or leave orphaned test rows still marked
    main for a future run to trip over.
    """
    before_ids = set(
        (await db_session.execute(select(DfEngineModelOptions.id).where(DfEngineModelOptions.is_main.is_(True))))
        .scalars()
        .all()
    )
    yield
    await db_session.rollback()  # see whatever the test committed via authed_client (REPEATABLE READ)
    current = (
        (await db_session.execute(select(DfEngineModelOptions).where(DfEngineModelOptions.is_main.is_(True))))
        .scalars()
        .all()
    )
    for row in current:
        if row.id not in before_ids:
            row.is_main = False
    for row_id in before_ids:
        row = await db_session.get(DfEngineModelOptions, row_id)
        if row is not None and not row.is_main:
            row.is_main = True
    await db_session.commit()


def _model_option_data(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    data = dict(
        uid=str(uuid4()),
        model_id=f"test-vendor/test-model-{unique}",
        name=f"SetMainTest-{unique}",
        type="text",
        is_available=True,
        is_enabled=False,
        is_main=False,
    )
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_set_main_success(authed_client, db_session):
    """200 OK; an available, enabled, non-main model can be set as main."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=True, is_main=False))

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}/main")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_main"] is True


@pytest.mark.asyncio
async def test_set_main_does_not_clear_other_main_same_type(authed_client, db_session):
    """200 OK; a type can have more than one main model — setting a new one leaves an existing main untouched."""
    old_main = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=True, is_main=True))
    new_main = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(type=old_main.type, is_enabled=True, is_main=False)
    )

    resp = await authed_client.call("PATCH", f"{URL}/{new_main.uid}/main")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_main"] is True

    await db_session.rollback()  # see the endpoint's own committed write (REPEATABLE READ)
    await db_session.refresh(old_main)
    assert old_main.is_main is True


@pytest.mark.asyncio
async def test_set_main_different_type_untouched(authed_client, db_session):
    """200 OK; setting a main for one type doesn't disturb another type's own main."""
    text_main = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(type="text", is_enabled=True, is_main=True)
    )
    image_candidate = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(type="image", is_enabled=True, is_main=False)
    )

    resp = await authed_client.call("PATCH", f"{URL}/{image_candidate.uid}/main")
    assert resp.status_code == 200

    await db_session.rollback()  # see the endpoint's own committed write (REPEATABLE READ)
    await db_session.refresh(text_main)
    assert text_main.is_main is True


@pytest.mark.asyncio
async def test_set_main_rejected_when_disabled(authed_client, db_session):
    """422 model_option_must_be_enabled_to_set_main when the model isn't enabled yet."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_available=True, is_enabled=False))

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}/main", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_must_be_enabled_to_set_main", "en")


@pytest.mark.asyncio
async def test_set_main_rejected_when_unavailable(authed_client, db_session):
    """422 model_option_unavailable_cannot_set_main takes precedence over the enabled check
    when the model is both unavailable and disabled."""
    row = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(is_available=False, is_enabled=False)
    )

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}/main", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_unavailable_cannot_set_main", "en")


@pytest.mark.asyncio
async def test_set_main_unknown_uid_is_404(authed_client):
    """404 model_option_not_found when the path uid matches no row."""
    resp = await authed_client.call("PATCH", f"{URL}/{uuid4()}/main", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("model_option_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, db_session):
    """401 when the request carries no bearer token."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=True))
    resp = await client.call("PATCH", f"{URL}/{row.uid}/main", raise_for_status=False)
    assert resp.status_code == 401
