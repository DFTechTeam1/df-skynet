"""`handle_chat_assistant` against fakes: the OpenRouter call, the DB session and the push."""

import json
from types import SimpleNamespace
import pytest
from services.mysql.model import DfEngineAttachments, DfEngineChatAssistants, DfEngineChatReferences
from services.rmq import consumer


def _reply(**flags):
    body = {"content": "answer", "attachments": [], "will_generate_prompt": False, "has_generation_prompt": False}
    body.update(flags)
    return json.dumps(body)


class FakeResult:
    status_code = 200

    def __init__(self, content):
        self.content = content

    def json(self):
        return {"choices": [{"message": {"content": self.content}}], "usage": {"total_tokens": 3, "cost": 0.5}}


class FakeDb:
    def __init__(self):
        self.added, self.statements, self.committed = [], [], False

    def add(self, row):
        row.id = 100
        self.added.append(row)

    def add_all(self, rows):
        for i, row in enumerate(rows):
            row.id = 200 + i
        self.added.extend(rows)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def execute(self, statement):
        self.statements.append(statement.compile().params)

    async def run_sync(self, fn):
        return 1

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def run(monkeypatch):
    pushes = []
    db = FakeDb()

    async def not_replayed(payload):
        return False

    monkeypatch.setattr(consumer, "replay_if_done", not_replayed)
    monkeypatch.setattr(consumer, "make_session", lambda url: db)
    monkeypatch.setattr(consumer, "send_chat_assistant", lambda *args: pushes.append(args))

    async def go(content, **payload):
        async def call(**kwargs):
            if isinstance(content, Exception):
                raise content
            return FakeResult(content)

        monkeypatch.setattr(consumer, "call_chat_assistant", call)
        base = {
            "content": [],
            "api_key": {"id": 1, "key": "k"},
            "model": {"id": 2, "model_id": "m"},
            "user_id": 3,
            "lang": "en",
            "session_id": 4,
            "session_uid": "s-uid",
            "chat_id": 5,
        }
        await consumer.handle_chat_assistant({**base, **payload})
        return SimpleNamespace(db=db, pushes=pushes, reply=db.added[0])

    return go


@pytest.mark.asyncio
async def test_a_plain_reply_is_stored_without_flags(run):
    out = await run(_reply())
    assert out.reply.will_generate_prompt is False and out.reply.has_generation_prompt is False
    assert out.db.statements == [] and out.pushes[0][0] == "success"


@pytest.mark.asyncio
async def test_a_reply_that_asks_is_stored_as_waiting(run):
    out = await run(_reply(will_generate_prompt=True))
    assert out.reply.will_generate_prompt is True and out.reply.has_generation_prompt is False


@pytest.mark.asyncio
async def test_a_written_prompt_is_never_also_waiting(run):
    out = await run(_reply(will_generate_prompt=True, has_generation_prompt=True), generate_prompt=True)
    assert out.reply.will_generate_prompt is False and out.reply.has_generation_prompt is True
    assert out.reply.content == "answer"


@pytest.mark.asyncio
async def test_a_prompt_written_without_a_yes_becomes_the_question(run):
    """The model wrote the prompt in a normal turn: the text is dropped, the reply asks first, no files are attached."""
    files = [{"id": 7, "sourceable_type": "DfEngineUploadFiles"}]
    out = await run(_reply(has_generation_prompt=True, content="SCENE: ..."), all_attachments=files)
    assert out.reply.has_generation_prompt is False and out.reply.will_generate_prompt is True
    assert "SCENE" not in out.reply.content and out.reply.content == consumer.resolve_message(
        "chat_assistant_confirm_generate_prompt", "en"
    )
    assert [type(r) for r in out.db.added].count(DfEngineChatReferences) == 0


@pytest.mark.asyncio
async def test_a_written_prompt_keeps_every_file(run):
    files = [{"id": 7, "sourceable_type": "DfEngineUploadFiles"}, {"id": 8, "sourceable_type": "DfEngineUploadFiles"}]
    out = await run(_reply(has_generation_prompt=True), generate_prompt=True, all_attachments=files)
    assert out.db.statements == []
    assert [type(r) for r in out.db.added].count(DfEngineChatReferences) == 2
    assert [type(r) for r in out.db.added].count(DfEngineAttachments) == 2


@pytest.mark.asyncio
async def test_a_failed_normal_message_is_marked_failed(run):
    out = await run("not json at all", attachments=[{"id": 1, "sourceable_type": "DfEngineUploadFiles"}])
    assert out.pushes[0][0] == "failed" and out.db.statements[0]["status_code"] == 502
    assert [type(r) for r in out.db.added].count(DfEngineChatReferences) == 1


@pytest.mark.asyncio
async def test_a_redelivered_message_is_skipped(monkeypatch):
    async def replayed(payload):
        return True

    monkeypatch.setattr(consumer, "replay_if_done", replayed)
    await consumer.handle_chat_assistant({})


@pytest.mark.asyncio
async def test_a_failed_yes_marks_the_user_bubble_failed_and_stores_the_error_reply(run):
    """The provider call raises: the user's message gets the failure status, an error reply is stored, a failed push goes out."""
    out = await run(consumer.ServiceError(), generate_prompt=True)
    assert out.pushes[0][0] == "failed"
    assert out.reply.status_code == 500 and out.reply.will_generate_prompt is False
    assert len(out.db.statements) == 1
    assert out.db.statements[0]["status_code"] == 500 and out.db.statements[0]["id_1"] == 5
