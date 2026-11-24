from services.chat_transcript import (
    CUT_MARKER,
    build_transcript,
    effective_chunk_tokens,
    estimate_tokens,
    model_window,
    single_call_limit,
    split_blocks,
)


def _row(role, content, status_code=200):
    return {"role": role, "content": content, "status_code": status_code}


def test_transcript_keeps_order_and_labels_and_skips_failed_and_system_rows():
    rows = [
        _row("system", "rules"),
        _row("user", "hi"),
        _row("assistant", "hello"),
        _row("user", "bad", 400),
        _row("assistant", "refused", 400),
        _row("user", "again", None),
    ]
    assert build_transcript(rows, 6000) == ["User: hi", "Assistant: hello", "User: again"]


def test_long_message_is_cut_with_a_marker():
    block = build_transcript([_row("assistant", "x" * 7000)], 6000)[0]
    assert block == "Assistant: " + "x" * 6000 + CUT_MARKER


def test_split_never_splits_a_block_and_every_chunk_fits():
    blocks = ["a" * 300, "b" * 300, "c" * 300, "d" * 300]  # 100 tokens each
    chunks = split_blocks(blocks, 250)
    assert chunks == [blocks[:2], blocks[2:]]
    assert all(sum(map(estimate_tokens, c)) <= 250 for c in chunks)
    assert [b for c in chunks for b in c] == blocks  # order kept


def test_oversize_block_gets_its_own_chunk():
    blocks = ["a" * 30, "b" * 3000, "c" * 30]
    assert split_blocks(blocks, 100) == [[blocks[0]], [blocks[1]], [blocks[2]]]


def test_real_sized_chat_chunk_counts():
    """Your DB averages: user ~84 characters, assistant ~2,987 (+ the label)."""

    def chat(messages):
        return ["User: " + "u" * 84, "Assistant: " + "a" * 2987] * (messages // 2)

    assert len(split_blocks(chat(500), 25_000)) == 11
    assert len(split_blocks(chat(400), 25_000)) == 9
    assert len(split_blocks(chat(100), 25_000)) == 3
    assert len(split_blocks(chat(500), 400_000)) == 1


def test_model_window_and_single_call_limit():
    big = {"context_length": 1_000_000, "max_completion_tokens": 64_000}
    mid = {"context_length": 200_000, "max_completion_tokens": 64_000}
    assert single_call_limit(300_000, big) == 300_000  # the cost cap wins
    assert single_call_limit(300_000, mid) == 129_200  # (200,000 - 64,000) * 95%
    for no_data in (None, {}, {"context_length": None}, {"context_length": 0}, {"max_completion_tokens": 5}):
        assert single_call_limit(300_000, no_data) == 0
    assert model_window({"context_length": 4000, "max_completion_tokens": 4000}) == 0  # nothing left after the reserve
    assert model_window({"context_length": 4000, "max_completion_tokens": 9000}) == 0  # never negative


def test_effective_chunk_tokens():
    assert effective_chunk_tokens(25_000, None) == 25_000
    assert effective_chunk_tokens(25_000, {"context_length": 0}) == 25_000
    assert effective_chunk_tokens(25_000, {"context_length": 1_000_000, "max_completion_tokens": 64_000}) == 25_000
    assert effective_chunk_tokens(25_000, {"context_length": 8_000, "max_completion_tokens": 2_000}) == 5_700
    assert (
        effective_chunk_tokens(25_000, {"context_length": 100, "max_completion_tokens": 99}) == 25_000
    )  # no window -> fixed
