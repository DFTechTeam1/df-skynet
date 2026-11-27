"""Fixtures shared by the generation create and image-edit tests. Import the ones a test file needs.

They work on real rows (project, PICs, admin settings), and put back whatever they change."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update

from services.mysql.factory.df_engine_api_keys import DfEngineApiKeysFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappingsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.model import DfEngineGenerations, DfEngineGuardrailValidations
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.mysql.model.df_engine_project_settings import DfEngineProjectSettings
from services.mysql.model.df_engine_settings import DfEngineSettings
from services.mysql.model.employees import Employees
from services.mysql.model.entertainment_task_songs import EntertainmentTaskSongs
from services.mysql.model.project_person_in_charges import ProjectPersonInCharges
from services.mysql.model.project_song_lists import ProjectSongLists
from services.redis import client as redis_client, delete_pattern

GUARDRAIL_RULES = [
    {"type": rule, "instruction": f"check {rule}"}
    for rule in ("prompt_injection", "nfsw", "image_generation", "video_generation")
]
GUARDRAIL_KEYS = ("assistant_model", "prompt_guardrails")


@pytest_asyncio.fixture
async def pic_employee_id(db_session, user_id) -> int:
    """The authenticated user's boss, resolved from the real `employees` row."""
    employee = (await db_session.execute(select(Employees).where(Employees.user_id == int(user_id)))).scalars().first()
    assert employee is not None and employee.boss_id is not None, "employee/boss_id missing for user_id"
    return employee.boss_id


@pytest_asyncio.fixture
async def project_lead(db_session, project_task, pic_employee_id):
    """Makes the boss the only lead PIC of the fixture task's project."""
    project_id = project_task.project_id
    of_project = ProjectPersonInCharges.project_id == project_id
    rows = (await db_session.execute(select(ProjectPersonInCharges).where(of_project))).scalars().all()
    previous = {row.id: row.is_lead for row in rows}
    # No branching on database state, so the same lines run whether or not the boss is already a PIC
    is_pic = any(row.pic_id == pic_employee_id for row in rows)
    added = [] if is_pic else [ProjectPersonInCharges(project_id=project_id, pic_id=pic_employee_id, is_lead=False)]
    db_session.add_all(added)
    await db_session.execute(update(ProjectPersonInCharges).where(of_project).values(is_lead=False))  # type: ignore
    await db_session.flush()
    await db_session.execute(
        update(ProjectPersonInCharges)
        .where(of_project, ProjectPersonInCharges.pic_id == pic_employee_id)  # type: ignore
        .values(is_lead=True)
    )
    await db_session.commit()
    try:
        yield
    finally:
        await db_session.execute(
            delete(ProjectPersonInCharges).where(ProjectPersonInCharges.id.in_([row.id for row in added]))  # type: ignore
        )
        for row_id, is_lead in previous.items():
            await db_session.execute(
                update(ProjectPersonInCharges).where(ProjectPersonInCharges.id == row_id).values(is_lead=is_lead)  # type: ignore
            )
        await db_session.commit()


@pytest_asyncio.fixture
async def pic_api_key(db_session, user_id, pic_employee_id, project_lead):
    """The lead's only main API key. Their real keys are set aside and put back afterwards."""
    of_lead = DfEngineApiKeys.employee_id == pic_employee_id
    saved = [row.model_dump() for row in (await db_session.execute(select(DfEngineApiKeys).where(of_lead))).scalars()]
    await db_session.execute(delete(DfEngineApiKeys).where(of_lead))
    await db_session.commit()

    key = DfEngineApiKeysFactory.create(employee_id=pic_employee_id, is_main=True, created_by=int(user_id))
    try:
        yield key
    finally:
        await db_session.execute(delete(DfEngineApiKeys).where(of_lead))
        db_session.add_all([DfEngineApiKeys(**data) for data in saved])
        await db_session.commit()


@pytest_asyncio.fixture
async def generation_menu_feature(user_id):
    """A menu with exactly one feature mapped under it."""
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)
    return menu, feature


@pytest_asyncio.fixture
async def image_model():
    """A usable image model with no parameters of its own that accepts one input image."""
    return DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.image,
        is_enabled=True,
        is_available=True,
        deleted_at=None,
        supported_parameters={"input_references": {"max": 1}},
    )


@pytest_asyncio.fixture
async def generation_project_settings(db_session, project_task):
    """Generous limits for the fixture task's project; a real row is put back afterwards."""
    of_project = DfEngineProjectSettings.project_id == project_task.project_id
    rows = (await db_session.execute(select(DfEngineProjectSettings).where(of_project))).scalars()
    saved = [row.model_dump() for row in rows]
    await db_session.execute(delete(DfEngineProjectSettings).where(of_project))
    db_session.add(
        DfEngineProjectSettings(
            project_id=project_task.project_id,
            token_usage_limit=1_000_000,
            compose_input_max_chars=100_000,
            storyboard_prompt_chars=1000,
            max_scene_per_storyboard=10,
            max_shot_per_scene=10,
            token_limit_threshold=1.0,
        )
    )
    await db_session.commit()
    try:
        yield
    finally:
        await db_session.execute(delete(DfEngineProjectSettings).where(of_project))
        db_session.add_all([DfEngineProjectSettings(**data) for data in saved])
        await db_session.commit()


@pytest_asyncio.fixture
async def guardrail(db_session, monkeypatch):
    """Turns the prompt guardrail on with a fake provider call. Set `flags` to change the verdict or
    `assistant_model` through `save` to change the settings; `calls` records every call made."""
    model = DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.text, is_enabled=True, is_available=True, deleted_at=None
    )
    of_keys = (DfEngineSettings.code == "admin_setting", DfEngineSettings.key.in_(GUARDRAIL_KEYS))  # type: ignore
    rows = (await db_session.execute(select(DfEngineSettings).where(*of_keys))).scalars()
    saved = [row.model_dump() for row in rows]
    last_validation = (await db_session.execute(select(func.max(DfEngineGuardrailValidations.id)))).scalar() or 0

    async def save(assistant_model):
        await db_session.execute(delete(DfEngineSettings).where(*of_keys))
        for key, value in (("assistant_model", assistant_model), ("prompt_guardrails", GUARDRAIL_RULES)):
            db_session.add(DfEngineSettings(code="admin_setting", key=key, value=json.dumps(value)))
        await db_session.commit()
        await delete_pattern(redis_client(), "settings:*")

    fake = SimpleNamespace(
        flags={"prompt_injection": False, "nfsw": False, "image_generation": True, "video_generation": True},
        calls=[],
        save=save,
    )

    async def call(**kwargs):
        fake.calls.append(kwargs)
        body = {
            "choices": [{"message": {"content": json.dumps(fake.flags)}}],
            "usage": {"total_tokens": 3, "cost": 0.0},
        }
        return SimpleNamespace(status_code=200, request=SimpleNamespace(content=b"{}"), json=lambda: body)

    monkeypatch.setattr("apps.controller.generations.call_prompt_guardrail", call)
    await save({"id": model.id, "model_id": model.model_id})
    try:
        yield fake
    finally:
        await db_session.execute(
            delete(DfEngineGuardrailValidations).where(DfEngineGuardrailValidations.id > last_validation)  # type: ignore
        )
        await db_session.execute(delete(DfEngineSettings).where(*of_keys))
        db_session.add_all([DfEngineSettings(**data) for data in saved])
        await db_session.commit()
        await delete_pattern(redis_client(), "settings:*")


@pytest.fixture
def fake_generation_backends(monkeypatch, guardrail):
    """Fakes the paid guardrail call and the Celery jobs. Returns the `.delay(...)` calls made."""
    delay_calls = []
    task = SimpleNamespace(delay=lambda *args, **kwargs: delay_calls.append((args, kwargs)))
    monkeypatch.setattr("apps.controller.generations.image_generation", task)
    monkeypatch.setattr("apps.controller.generations.video_generation", task)
    return delay_calls


@pytest_asyncio.fixture
async def make_song(db_session, project_task, user_id):
    """Factory for a song with one assignment, on the same project as `project_task`.
    The assignment belongs to the authenticated user unless `employee_id` is given."""
    employee = (await db_session.execute(select(Employees).where(Employees.user_id == int(user_id)))).scalars().first()
    created = []

    async def _make(status: int, employee_id=None) -> ProjectSongLists:
        song = ProjectSongLists(
            uid=str(uuid4()),
            project_id=project_task.project_id,
            name="Test Song",
            is_request_edit=False,
            is_request_delete=False,
            created_by=int(user_id),
        )
        db_session.add(song)
        await db_session.flush()
        assignment = EntertainmentTaskSongs(
            project_song_list_id=song.id,
            status=status,
            employee_id=employee_id or employee.id,
            project_id=project_task.project_id,
        )
        db_session.add(assignment)
        await db_session.commit()
        created.append((song.id, assignment.id))
        return song

    try:
        yield _make
    finally:
        for song_id, assignment_id in created:
            await db_session.execute(delete(EntertainmentTaskSongs).where(EntertainmentTaskSongs.id == assignment_id))
            # generations made against the song reference it, so they go first
            await db_session.execute(delete(DfEngineGenerations).where(DfEngineGenerations.song_id == song_id))
            await db_session.execute(delete(ProjectSongLists).where(ProjectSongLists.id == song_id))
        await db_session.commit()


@pytest.fixture
def override_repo(monkeypatch):
    """`override_repo(Repo, "method", change)` runs the real lookup, then lets `change` edit the record,
    so one status or relation can be faked without touching real rows."""

    def _override(repo, method, change):
        real = getattr(repo, method)

        async def wrapper(self, *args, **kwargs):
            record = await real(self, *args, **kwargs)
            if isinstance(record, dict):
                change(record)
            return record

        monkeypatch.setattr(repo, method, wrapper)

    return _override


def payload(menu, feature, model, **overrides):
    return {
        "prompt": "a scenic mountain view at sunrise",
        "model_uid": str(model.uid),
        "menu_uid": str(menu.uid),
        "feature_uid": str(feature.uid),
        "references": [],
        "type": "image",
        "parameter": {},
        **overrides,
    }
