from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from celery.exceptions import Retry
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.search import docs, dispatch, query
from services.search.base import SearchResult, SearchHit
from services.tasks import search_sync

NOW = datetime(2026, 10, 17, 10, 0)
USER = {"id": 7, "image": None, "employees": {"nickname": "z"}}


def _result(**over):
    generation = SimpleNamespace(
        kind=over.pop("kind", GenerationKinds.image), status=over.pop("status", GenerationStatuses.success)
    )
    return SimpleNamespace(generation=generation, is_main=over.pop("is_main", True), **over)


def test_generation_qualifies_only_main_successful_media():
    assert docs.generation_qualifies(_result())
    assert docs.generation_qualifies(_result(kind=GenerationKinds.video))
    assert not docs.generation_qualifies(_result(is_main=False))
    assert not docs.generation_qualifies(_result(kind=GenerationKinds.element))
    assert not docs.generation_qualifies(_result(status=GenerationStatuses.failed))
    assert not docs.generation_qualifies(SimpleNamespace(generation=None, is_main=True))


def test_upload_qualifies_only_images():
    assert docs.upload_qualifies(SimpleNamespace(type=UploadFileTypes.image))
    assert not docs.upload_qualifies(SimpleNamespace(type=UploadFileTypes.video))
    assert not docs.upload_qualifies(SimpleNamespace(type=UploadFileTypes.folder))


def test_load_options_are_built():
    assert len(docs.generation_load_options()) == 7 and len(docs.upload_load_options()) == 5


def test_build_generation_doc_is_flat_with_null_action(monkeypatch):
    row = {
        "id": 7,
        "uid": "r1",
        "parent_id": None,
        "name": "a.png",
        "path": "storage/x/a.png",
        "size": 10,
        "is_main": True,
        "version": 1,
        "created_at": NOW.isoformat(),
        "updated_at": None,
        "favourited_at": None,
        "archieved_at": None,
        "created_by_user": USER,
        "updated_by_user": None,
        "generation": {
            "uid": "g1",
            "kind": "image",
            "status": "success",
            "cost": 0.5,
            "prompt": "p",
            "full_prompt": "fp",
            "parameter": {"n": 1},
            "model_option": {"name": "m"},
            "task": {"uid": "t1", "name": "Task"},
            "song": None,
            "project": {"uid": "p1"},
        },
    }
    monkeypatch.setattr(docs, "serialize", lambda _: row)
    doc = docs.build_generation_doc(object())
    assert doc["objectID"] == "r1" and doc["project_uid"] == "p1" and doc["task_uid"] == "t1"
    assert doc["action"] is None and "variants" not in doc and "references" not in doc
    assert doc["creator"]["user_id"] == 7 and doc["task"] == "Task"


def test_build_upload_doc_falls_back_to_song_name(monkeypatch):
    row = {
        "id": 9,
        "uid": "u1",
        "name": "a.png",
        "path": "storage/x/upload/images/a.png",
        "type": "image",
        "size": 2048,
        "created_at": NOW.isoformat(),
        "updated_at": None,
        "created_by_user": USER,
        "updated_by_user": None,
        "task": None,
        "song": {"uid": "s1", "name": "Song"},
        "project": {"uid": "p1"},
    }
    monkeypatch.setattr(docs, "serialize", lambda _: row)
    doc = docs.build_upload_doc(object())
    assert (
        doc["id"] == 9
        and doc["objectID"] == "u1"
        and doc["song_uid"] == "s1"
        and doc["task"] == "Song"
        and doc["action"] is None
    )


# --- tasks -------------------------------------------------------------------------------------------------------
class FakeDB:
    def __init__(self, row):
        self.row, self.executed = row, []

    def query(self, *_):
        return self

    def options(self, *_):
        return self

    def filter(self, *_):
        return self

    def first(self):
        return self.row

    def execute(self, stmt):
        self.executed.append(stmt)


@pytest.fixture
def engine(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(search_sync, "get_search_engine", lambda: fake)
    return fake


def _db(monkeypatch, row):
    db = FakeDB(row)

    @contextmanager
    def fake():
        yield db

    monkeypatch.setattr(search_sync, "get_sync_db", fake)
    return db


def test_upsert_indexes_a_qualifying_upload(monkeypatch, engine):
    db = _db(monkeypatch, SimpleNamespace(id=1, uid="u1", type=UploadFileTypes.image, updated_at=None))
    monkeypatch.setattr(search_sync, "build_upload_doc", lambda r: {"objectID": r.uid})
    out = search_sync.search_upsert.run("upload", "u1")
    assert out["action"] == "upserted"
    engine.upsert.assert_called_once_with("uploaded_files", [{"objectID": "u1"}])
    assert len(db.executed) == 1


def test_upsert_indexes_a_qualifying_generation(monkeypatch, engine):
    _db(monkeypatch, _result(id=1, uid="r1", updated_at=None))
    monkeypatch.setattr(search_sync, "build_generation_doc", lambda r: {"objectID": r.uid})
    assert search_sync.search_upsert.run("generation", "r1")["action"] == "upserted"
    engine.upsert.assert_called_once_with("main_generations", [{"objectID": "r1"}])


def test_upsert_removes_a_row_that_stopped_qualifying(monkeypatch, engine):
    db = _db(monkeypatch, _result(id=1, uid="r1", is_main=False, updated_at=None))
    assert search_sync.search_upsert.run("generation", "r1")["action"] == "deleted"
    engine.delete.assert_called_once_with("main_generations", ["r1"])
    assert "indexed_at" in str(db.executed[0].compile().params)


def test_upsert_removes_a_missing_row(monkeypatch, engine):
    _db(monkeypatch, None)
    assert search_sync.search_upsert.run("upload", "gone")["action"] == "deleted"
    engine.delete.assert_called_once_with("uploaded_files", ["gone"])


@contextmanager
def _request(task, retries, args):
    """Run a task the way a worker does: `called_directly=False` makes `self.retry` raise `Retry` instead of the error."""
    task.push_request(retries=retries, called_directly=False, args=args, kwargs={}, is_eager=False)
    try:
        yield
    finally:
        task.pop_request()


def test_upsert_retries_then_gives_up(monkeypatch, engine):
    _db(monkeypatch, None)
    engine.delete.side_effect = RuntimeError("algolia down")
    with _request(search_sync.search_upsert, 0, ("upload", "u1")), pytest.raises(Retry):
        search_sync.search_upsert.run("upload", "u1")
    with (
        _request(search_sync.search_upsert, search_sync.search_upsert.max_retries, ("upload", "u1")),
        pytest.raises(RuntimeError),
    ):
        search_sync.search_upsert.run("upload", "u1")


def test_delete_task(engine):
    assert search_sync.search_delete.run("uploaded_files", ["a", "b"]) == {"index": "uploaded_files", "deleted": 2}
    engine.delete.assert_called_once_with("uploaded_files", ["a", "b"])


def test_delete_task_retries_then_gives_up(engine):
    engine.delete.side_effect = RuntimeError("down")
    with _request(search_sync.search_delete, 0, ("uploaded_files", ["a"])), pytest.raises(Retry):
        search_sync.search_delete.run("uploaded_files", ["a"])
    with (
        _request(search_sync.search_delete, search_sync.search_delete.max_retries, ("uploaded_files", ["a"])),
        pytest.raises(RuntimeError),
    ):
        search_sync.search_delete.run("uploaded_files", ["a"])


def test_backfill_queues_what_is_not_indexed(monkeypatch):
    class Q:
        def __init__(self, rows):
            self.rows = rows

        def join(self, *_):
            return self

        def filter(self, *_):
            return self

        def limit(self, *_):
            return self

        def all(self):
            return self.rows

    queues = iter([Q([("r1",), ("r2",)]), Q([("u1",)])])
    db = SimpleNamespace(query=lambda *_: next(queues))

    @contextmanager
    def fake():
        yield db

    monkeypatch.setattr(search_sync, "get_sync_db", fake)
    delay = MagicMock()
    monkeypatch.setattr(search_sync.search_upsert, "delay", delay)
    assert search_sync.search_backfill() == {"generations": 2, "uploads": 1}
    assert [c.args for c in delay.call_args_list] == [("generation", "r1"), ("generation", "r2"), ("upload", "u1")]


def test_worker_start_configures_both_indexes(engine):
    search_sync.ensure_index_settings()
    assert [c.args[0] for c in engine.configure_index.call_args_list] == ["main_generations", "uploaded_files"]
    assert engine.configure_index.call_args.args[1:] == (docs.SEARCHABLE_FIELDS, docs.FILTER_FIELDS)


def test_worker_start_survives_algolia_failure(engine):
    engine.configure_index.side_effect = RuntimeError("down")
    search_sync.ensure_index_settings()  # logged, must not raise


# --- dispatcher ---------------------------------------------------------------------------------------------------
async def test_dispatch_commits_then_queues(monkeypatch):
    db = SimpleNamespace(commit=AsyncMock())
    upsert, delete = MagicMock(), MagicMock()
    monkeypatch.setattr(dispatch.search_upsert, "delay", upsert)
    monkeypatch.setattr(dispatch.search_delete, "delay", delete)
    await dispatch.dispatch_search_sync(db, generations=["g", "g"], uploads=["u"], deleted_uploads=["d"])
    db.commit.assert_awaited_once()
    assert [c.args for c in upsert.call_args_list] == [("generation", "g"), ("upload", "u")]
    delete.assert_called_once_with("uploaded_files", ["d"])


async def test_dispatch_does_nothing_without_changes():
    db = SimpleNamespace(commit=AsyncMock())
    await dispatch.dispatch_search_sync(db)
    db.commit.assert_not_awaited()


async def test_dispatch_skips_delete_task_without_deletions(monkeypatch):
    db = SimpleNamespace(commit=AsyncMock())
    delete = MagicMock()
    monkeypatch.setattr(dispatch.search_delete, "delay", delete)
    monkeypatch.setattr(dispatch.search_upsert, "delay", MagicMock())
    await dispatch.dispatch_search_sync(db, uploads=["u"])
    delete.assert_not_called()


# --- read side ----------------------------------------------------------------------------------------------------
def _gen(owner=7, kind="image", **over):
    return {
        "objectID": "r1",
        "project_uid": "p1",
        "file_uid": "r1",
        "kind": kind,
        "path": "http://u/a.png",
        "is_main": True,
        "archieved_at": None,
        "favourited_at": None,
        "creator": {"user_id": owner},
        "action": None,
        **over,
    }


def test_generation_action_follows_creator_then_override():
    mine = query.generation_with_action(_gen(owner=7), 7, False)
    theirs = query.generation_with_action(_gen(owner=8), 7, False)
    override = query.generation_with_action(_gen(owner=8), 7, True)
    assert mine["action"]["can_rename"] and not theirs["action"]["can_rename"] and override["action"]["can_rename"]
    assert "objectID" not in mine and "project_uid" not in mine and mine["variants"] == [] and mine["references"] == []


def test_upload_action_follows_creator_then_override():
    doc = {"objectID": "u1", "project_uid": "p1", "kind": "image", "creator": {"user_id": 8}, "action": None}
    assert not query.upload_with_action(doc, 7, False)["action"]["can_delete"]
    assert query.upload_with_action(doc, 7, True)["action"]["can_delete"]
    assert query.upload_with_action({**doc, "creator": None}, 8, False)["action"]["can_delete"] is False


def _engine(monkeypatch, *hit_lists):
    results = [
        SearchResult(hits=[SearchHit(id=d["objectID"], data=d) for d in docs_], total=len(docs_)) for docs_ in hit_lists
    ]
    fake = MagicMock()
    fake.search.return_value = results
    monkeypatch.setattr(query, "get_search_engine", lambda: fake)
    return fake


async def test_search_project_files_scopes_and_filters(monkeypatch):
    upload = {"objectID": "u1", "kind": "image", "creator": {"user_id": 7}}
    fake = _engine(monkeypatch, [upload], [_gen(), _gen(owner=8, objectID="r2")])
    uploads, generations = await query.search_project_files("p1", "cat", ("image", "image_edit"), 7, False)
    assert len(uploads) == 1 and len(generations) == 2
    uploads_req, generations_req = fake.search.call_args.args[0]
    assert uploads_req.index == "uploaded_files" and generations_req.index == "main_generations"
    assert uploads_req.restrict_attributes == ["name", "path", "task"]
    assert generations_req.filter.items[0].value == "p1"


async def test_search_project_files_personal(monkeypatch):
    _engine(
        monkeypatch, [{"objectID": "u1", "kind": "image", "creator": {"user_id": 8}}], [_gen(owner=8), _gen(owner=7)]
    )
    uploads, generations = await query.search_project_files("p1", "cat", ("image",), 7, False, personal_file=True)
    assert uploads == [] and len(generations) == 1


async def test_search_task_generations(monkeypatch):
    fake = _engine(monkeypatch, [_gen(owner=8), _gen(owner=7)])
    out = await query.search_task_generations("t1", "cat", 7, False)
    assert len(out) == 2
    request = fake.search.call_args.args[0][0]
    assert request.restrict_attributes == ["name", "path"]
    assert [i.field for i in request.filter.items[0].items] == ["task_uid", "song_uid"]
    _engine(monkeypatch, [_gen(owner=8), _gen(owner=7)])
    assert len(await query.search_task_generations("t1", "cat", 7, False, personal_file=True)) == 1


def test_group_reference_picker_keeps_action_and_drops_videos_folders_and_hidden_fields():
    groups = query.group_reference_picker(
        [{"kind": "image", "prompt": "x", "action": {}, "name": "a"}, {"kind": "video", "name": "v"}],
        [
            {"kind": "image", "action": {}, "name": "u"},
            {"kind": "video", "name": "uv"},
            {"kind": "folder", "name": "f"},
        ],
    )
    assert [g["type"] for g in groups] == ["Image Generations", "Image Uploads", "Elements", "Shared"]
    assert groups[0] == {
        "type": "Image Generations",
        "total": 1,
        "files": [{"kind": "image", "action": {}, "name": "a"}],
    }
    assert groups[1]["files"] == [{"kind": "image", "action": {}, "name": "u"}] and groups[2]["total"] == 0
