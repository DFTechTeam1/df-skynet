from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.tasks import udin_sweep, udin_uploader


@contextmanager
def _db(upload):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = upload
    yield db


def _bump(upload, final, attempts):
    upload.sweep_attempts = attempts
    with patch.object(udin_uploader, "get_sync_db", lambda: _db(upload)):
        udin_uploader._bump_sweep_attempts(1, final=final, detail="x")


def _upload():
    return SimpleNamespace(id=1, sweep_attempts=0, needs_reconciliation=False, upload_status=UploadStatuses.pending)


def test_sweep_cap_is_one_run_of_six_attempts():
    assert udin_sweep.MAX_SWEEP_ATTEMPTS == udin_uploader.MAX_SWEEP_ATTEMPTS == 12


def test_final_bump_below_cap_stays_pending():
    upload = _upload()
    _bump(upload, final=True, attempts=5)
    assert upload.sweep_attempts == 6
    assert upload.needs_reconciliation is True
    assert upload.upload_status == UploadStatuses.pending


def test_final_bump_reaching_cap_marks_failed():
    upload = _upload()
    _bump(upload, final=True, attempts=11)
    assert upload.upload_status == UploadStatuses.failed


def test_non_final_bump_never_marks_failed():
    upload = _upload()
    _bump(upload, final=False, attempts=11)
    assert upload.sweep_attempts == 12
    assert upload.needs_reconciliation is False
    assert upload.upload_status == UploadStatuses.pending


def test_sweep_requeues_each_candidate():
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.all.return_value = [(1, 10), (2, 20)]
    with (
        patch.object(udin_sweep, "get_sync_db", lambda: _db_ctx(db)),
        patch.object(udin_sweep.udin_uploader, "delay") as delay,
    ):
        assert udin_sweep.udin_sweep() == {"requeued": 2}
    assert [c.args for c in delay.call_args_list] == [(1, 10), (2, 20)]


@contextmanager
def _db_ctx(db):
    yield db


def test_bump_creates_the_upload_row_when_missing():
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    with patch.object(udin_uploader, "get_sync_db", lambda: _db_ctx(db)):
        udin_uploader._bump_sweep_attempts(1)
    created = db.add.call_args.args[0]
    assert created.generation_id == 1 and created.sweep_attempts == 1
