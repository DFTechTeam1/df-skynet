import pytest
from sqlalchemy import select
from services.mysql.model import DfEngineChatAssistants
from services.openrouter import GENERATE_PROMPT_INSTRUCTION
from tests.helpers import attach_upload, feature_prompts, make_chat_session
from middlewares.lang import resolve_message
from schemas.payload.feature_management import FeatureTypes


def _url(session):
    return f"/api/chat-assistants/{session.uid}"


def _asked_chat(ctx, user_id, **extra):
    """A user request answered by an assistant reply that asks whether to write the prompt."""
    return make_chat_session(
        ctx,
        user_id,
        [("user", "make a prompt"), ("assistant", "Write it now?", {"will_generate_prompt": True, **extra})],
    )


async def _post(authed_client, session, generate_prompt=True, content="Yes, write it"):
    return await authed_client.call(
        "POST", _url(session), json={"content": content, "generate_prompt": generate_prompt}, raise_for_status=False
    )


@pytest.mark.asyncio
async def test_yes_stores_guidelines_and_the_user_bubble_and_publishes(
    authed_client, db_session, chat_ctx, chat_settings, chat_features, user_id, chat_calls
):
    """200; the yes is a normal user bubble, the enhance_prompt templates become system rows (no creator), the
    user's yes closes the sent messages without being stored, and the worker is told it is a generate-prompt call."""
    await chat_settings()
    session, rows = _asked_chat(chat_ctx, user_id)
    file = attach_upload(rows[0], user_id, chat_ctx.project_id)
    resp = await _post(authed_client, session)
    assert resp.status_code == 200, resp.text
    yes_uid = resp.json()["data"]
    assert chat_calls.insertions == [("success", str(session.uid), yes_uid)]
    assert chat_calls.events == ["insertion", "publish"]

    guidelines = await feature_prompts(db_session, FeatureTypes.enhance_prompt)
    stored = (
        (
            await db_session.execute(
                select(DfEngineChatAssistants)  # type: ignore
                .where(DfEngineChatAssistants.session_id == session.id)  # type: ignore
                .order_by(DfEngineChatAssistants.id)  # type: ignore
            )
        )
        .scalars()
        .all()
    )
    system_rows = [r for r in stored if r.role == "system"]
    assert [r.content for r in system_rows] == guidelines and {r.created_by for r in system_rows} <= {None}
    assert stored[-1].uid == yes_uid and stored[-1].role == "user" and stored[-1].content == "Yes, write it"
    assert not any(r.will_generate_prompt for r in stored)  # the question was answered: the state is refreshed
    assert GENERATE_PROMPT_INSTRUCTION.strip() not in [r.content for r in stored]

    message = chat_calls.published[0]
    assert message["type"] == "chat_assistant" and message["generate_prompt"] is True
    assert message["chat_id"] == stored[-1].id
    assert {a["uid"] for a in message["all_attachments"]} == {file.uid}
    *_, yes_turn, instruction = message["content"]
    assert yes_turn["role"] == "user" and yes_turn["content"][0]["text"] == "Yes, write it"
    assert instruction["role"] == "user" and instruction["content"][0]["text"] == GENERATE_PROMPT_INSTRUCTION.strip()
    sent_system = [m["content"][0]["text"] for m in message["content"] if m["role"] == "system"]
    assert sent_system[len(sent_system) - len(guidelines) :] == guidelines


@pytest.mark.asyncio
async def test_without_the_flag_nothing_changes(
    authed_client, db_session, chat_ctx, chat_settings, user_id, chat_calls
):
    """200; a normal message adds no guidelines and no confirmation turn, even when a question is waiting."""
    await chat_settings()
    session, rows = _asked_chat(chat_ctx, user_id)
    resp = await _post(authed_client, session, generate_prompt=False, content="not yet")
    assert resp.status_code == 200, resp.text
    message = chat_calls.published[0]
    assert message["generate_prompt"] is False and message["content"][-1]["content"][0]["text"] == "not yet"
    system_rows = (
        (
            await db_session.execute(
                select(DfEngineChatAssistants.id).where(  # type: ignore
                    DfEngineChatAssistants.session_id == session.id,
                    DfEngineChatAssistants.role == "system",  # type: ignore
                )
            )
        )
        .scalars()
        .all()
    )
    assert system_rows == []
    waiting = (
        await db_session.execute(
            select(DfEngineChatAssistants.will_generate_prompt).where(DfEngineChatAssistants.id == rows[1].id)
        )  # type: ignore
    ).scalar()
    assert waiting is True  # a normal message does not answer the question


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra, role",
    [
        ({"will_generate_prompt": False}, "assistant"),  # nothing waiting
        ({"status_code": 502}, "assistant"),  # a failed reply
        ({}, "user"),  # a user row never counts
    ],
)
async def test_yes_without_a_waiting_question_is_422(
    authed_client, chat_ctx, chat_settings, user_id, chat_calls, extra, role
):
    await chat_settings()
    session, _ = make_chat_session(
        chat_ctx, user_id, [("user", "hi"), (role, "ask", {"will_generate_prompt": True, **extra})]
    )
    resp = await _post(authed_client, session)
    assert resp.status_code == 422 and chat_calls.events == []


@pytest.mark.asyncio
async def test_yes_without_an_enhance_prompt_feature_is_404(
    authed_client, chat_ctx, chat_settings, user_id, chat_calls, monkeypatch
):
    await chat_settings()
    monkeypatch.setattr(
        "apps.controller.chat_assistants.FeatureTypes", type("F", (), {"enhance_prompt": "no_such_type"})
    )
    session, _ = _asked_chat(chat_ctx, user_id)
    resp = await _post(authed_client, session)
    assert resp.status_code == 404 and chat_calls.events == []
    assert resp.json()["message"] == resolve_message("enhance_prompt_feature_not_configured", "en")


# ---- the guards shared with continue / resend: each is forced by editing what the real repository call returned ----
def _patch(monkeypatch, repo, name, mutate):
    original = getattr(repo, name)

    async def wrapped(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        changed = mutate(result, kwargs)
        return result if changed is None else changed

    monkeypatch.setattr(repo, name, wrapped)


def _without_setting(*keys):
    def mutate(rows, kwargs):
        return [row for row in rows if row["key"] not in keys]

    return mutate


def _edit_setting(key, edit):
    def mutate(rows, kwargs):
        for row in rows:
            if row["key"] == key:
                edit(row)
        return rows

    return mutate


def _edit_project(edit):
    def mutate(project, kwargs):
        edit(project)
        return project

    return mutate


def _second_lead(project):
    project["project_person_in_charges"].append({**project["project_person_in_charges"][0], "is_lead": True})


def _no_lead(project):
    for pic in project["project_person_in_charges"]:
        pic["is_lead"] = False


def _lead_key_twice(project):
    pic = next(p for p in project["project_person_in_charges"] if p["is_lead"])["pic"]
    pic["api_keys"] = [*pic["api_keys"], *pic["api_keys"]]


def _lead_without_key(project):
    next(p for p in project["project_person_in_charges"] if p["is_lead"])["pic"]["api_keys"] = []


def _no_project_setting(project):
    project["project_setting"] = None


def _other_class_limit(row):
    row["value"] = [{**limit, "id": -1} for limit in row["value"]]


def _with_project_setting(project):
    project["project_setting"] = {"token_usage_limit": 10**9, "token_limit_threshold": 1}


GUARDS = [
    ("default_model_not_configured", "settings", _without_setting("assistant_model")),
    ("chat_assistant_settings_not_configured", "settings", _without_setting("chat_assistant_settings")),
    ("project_class_not_assigned", "project", _edit_project(lambda p: p.update(project_class_id=None))),
    ("project_action_requires_ongoing", "project", _edit_project(lambda p: p.update(status=-1))),
    ("project_pic_not_assigned", "project", _edit_project(lambda p: p.update(project_person_in_charges=[]))),
    ("project_lead_not_assigned", "project", _edit_project(_no_lead)),
    ("project_lead_multiple", "project", _edit_project(_second_lead)),
    ("project_lead_api_key_not_found", "project", _edit_project(_lead_without_key)),
    ("project_lead_api_key_multiple", "project", _edit_project(_lead_key_twice)),
    (
        "global_project_setting_not_configured",
        "settings_and_project",
        (_without_setting("project_class_limitations"), _edit_project(_no_project_setting)),
    ),
    (
        "project_class_limitation_not_found",
        "settings_and_project",
        (_edit_setting("project_class_limitations", _other_class_limit), _edit_project(_no_project_setting)),
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("message, kind, mutate", GUARDS, ids=[g[0] for g in GUARDS])
async def test_continue_generate_prompt_refuses_when_a_shared_guard_fails(
    authed_client, chat_ctx, chat_settings, chat_features, user_id, chat_calls, monkeypatch, message, kind, mutate
):
    """422 and nothing published for each guard `message` names."""
    from services.repository.projects import ProjectRepository
    from services.repository.admin_settings import AdminSettingRepository

    await chat_settings()
    if kind == "settings":
        _patch(monkeypatch, AdminSettingRepository, "get_setting", mutate)
    elif kind == "project":
        _patch(monkeypatch, ProjectRepository, "get_project", mutate)
    else:
        _patch(monkeypatch, AdminSettingRepository, "get_setting", mutate[0])
        _patch(monkeypatch, ProjectRepository, "get_project", mutate[1])
    session, _ = _asked_chat(chat_ctx, user_id)
    resp = await _post(authed_client, session)
    assert resp.status_code == 422, resp.text
    assert chat_calls.events == []


@pytest.mark.asyncio
async def test_continue_generate_prompt_refuses_a_user_without_an_employee(
    authed_client, chat_ctx, chat_settings, chat_features, user_id, chat_calls, monkeypatch
):
    from services.repository.users import UserRepository

    await chat_settings()
    _patch(monkeypatch, UserRepository, "get_user", lambda user, kwargs: {**user, "employees": None})
    session, _ = _asked_chat(chat_ctx, user_id)
    resp = await _post(authed_client, session)
    assert resp.status_code == 422 and chat_calls.events == []


@pytest.mark.asyncio
async def test_continue_generate_prompt_refuses_when_the_project_cost_limit_is_exceeded(
    authed_client, chat_ctx, chat_settings, chat_features, user_id, chat_calls, monkeypatch
):
    from services.repository.chat_assistants import ChatAssistantRepository

    await chat_settings()
    _patch(
        monkeypatch,
        ChatAssistantRepository,
        "get_chat_assistant",
        lambda row, kwargs: {"project_id": chat_ctx.project_id, "total_cost": 10**9} if "group_by" in kwargs else None,
    )
    session, _ = _asked_chat(chat_ctx, user_id)
    resp = await _post(authed_client, session)
    assert resp.status_code == 422 and chat_calls.events == []


def _as_employee(employee_id, boss_id=None):
    return lambda user, kwargs: {**user, "employees": {**user["employees"], "id": employee_id, "boss_id": boss_id}}


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["own", "transfer", "boss", "lead", "project_setting"])
async def test_continue_generate_prompt_resolves_an_api_key_for_every_kind_of_member(
    authed_client, chat_ctx, chat_settings, chat_features, user_id, chat_calls, monkeypatch, source
):
    """200 whichever way the user's key is found: own key, the transfer requester's, the boss's, or the lead's."""
    from services.repository.projects import ProjectRepository
    from services.repository.users import UserRepository

    await chat_settings()
    lead_pic_id = {}

    def see_project(project, kwargs):
        lead_pic_id["id"] = next(p for p in project["project_person_in_charges"] if p["is_lead"])["pic_id"]
        if source == "transfer":
            project["transfer_team_members"] = [{"employee_id": 987654, "requested_by": lead_pic_id["id"]}]
        if source == "project_setting":
            _with_project_setting(project)
        return project

    _patch(monkeypatch, ProjectRepository, "get_project", see_project)

    def as_member(user, kwargs):
        employee = {"own": lead_pic_id["id"], "transfer": 987654}.get(source, 987654)
        boss = lead_pic_id["id"] if source == "boss" else None
        return _as_employee(employee, boss)(user, kwargs)

    _patch(monkeypatch, UserRepository, "get_user", as_member)
    session, _ = _asked_chat(chat_ctx, user_id)
    resp = await _post(authed_client, session)
    assert resp.status_code == 200, resp.text
    assert chat_calls.published[0]["api_key"]["employee_id"] == lead_pic_id["id"]


@pytest.mark.asyncio
async def test_continue_generate_prompt_answers_500_when_the_publish_fails(
    authed_client, chat_ctx, chat_settings, chat_features, user_id, chat_calls, monkeypatch
):
    async def boom(message):
        raise RuntimeError("queue down")

    monkeypatch.setattr("apps.controller.chat_assistants.publish_message", boom)
    await chat_settings()
    session, _ = _asked_chat(chat_ctx, user_id)
    resp = await _post(authed_client, session)
    assert resp.status_code == 500
