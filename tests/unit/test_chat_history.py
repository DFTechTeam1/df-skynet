from schemas.format.chat_assistants import build_history


def _ref(uid):
    return {"attachment": {"upload_file": {"uid": uid, "name": "n", "path": f"{uid}.png"}, "generation_result": None}}


def _row(role, content, status_code=200, refs=()):
    return {"role": role, "content": content, "status_code": status_code, "chat_references": [_ref(u) for u in refs]}


def test_system_first_then_turns_in_order():
    rows = [
        _row("system", "base"),
        _row("user", "hi A", refs=["A"]),
        _row("assistant", "reply 1"),
        _row("system", "params"),
        _row("user", "again"),
    ]
    out = build_history(rows)
    assert [m["role"] for m in out] == ["system", "system", "user", "assistant", "user"]
    assert out[0]["content"][0]["text"] == "base" and out[1]["content"][0]["text"] == "params"
    assert out[3]["content"] == [{"type": "text", "text": "reply 1"}]


def test_user_images_are_sent_again_with_marker():
    out = build_history([_row("user", "look A", refs=["A"])])
    parts = out[0]["content"]
    assert parts[0]["text"] == "look A"
    assert parts[1]["text"].startswith("[uid=A url=") and parts[1]["text"].endswith("source=upload]")
    assert parts[2]["type"] == "image_url"


def test_failed_reply_and_blocked_message_are_skipped():
    rows = [
        _row("user", "bad", status_code=400),
        _row("assistant", "refused", status_code=400),
        _row("user", "good"),
        _row("assistant", "ok"),
        _row("assistant", "failed", status_code=502),
    ]
    out = build_history(rows)
    assert [m["content"][0]["text"] for m in out] == ["good", "ok"]


def test_null_status_code_counts_as_ok():
    assert len(build_history([_row("user", "x", status_code=None)])) == 1
