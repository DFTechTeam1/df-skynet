from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from services.dto.asynced import generation_files
from services.redis import CacheKeys


def _row(id_):
    return SimpleNamespace(id=id_)


def _record(uid):
    return {
        "kind": "image",
        "uid": uid,
        "status": "success",
        "cost": 0.01,
        "model_option": None,
        "prompt": "p",
        "full_prompt": "p",
        "parameter": {},
        "created_at": datetime(2026, 10, 24),
        "created_by_user": None,
    }


@pytest.mark.asyncio
async def test_can_reupload_false_only_while_lock_is_held():
    ctx = SimpleNamespace(
        db=MagicMock(), key=CacheKeys(), redis=MagicMock(mget=AsyncMock(return_value=[None, "sweep"]))
    )
    with (
        patch.object(generation_files, "query", AsyncMock(return_value=[_row(1), _row(2)])),
        patch.object(generation_files, "serialize", return_value=[_record("a"), _record("b")]),
        patch.object(generation_files, "format_user_employees", return_value=None),
    ):
        items = await generation_files.get_failed_upload_generations(ctx, 1, True)
    assert [i["action"]["can_reupload"] for i in items] == [True, False]
    ctx.redis.mget.assert_awaited_once_with(
        [CacheKeys().generation_reupload_lock(1), CacheKeys().generation_reupload_lock(2)]
    )
