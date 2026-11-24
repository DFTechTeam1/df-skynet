"""Pure helpers that turn a chat into text and size it for the transfer-knowledge summary calls."""

from typing import Any, Optional

CUT_MARKER = " [...cut...]"
MARGIN_PERCENT = 95  # keep 5% of the usable window free for the instruction and the JSON wrapper
CHARS_PER_TOKEN = 3  # pessimistic: Indonesian text and emoji use more tokens per character than English


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def build_transcript(rows: list[dict[str, Any]], max_message_chars: int) -> list[str]:
    """One text block per answered user/assistant row, oldest first; blocked and failed rows are left out."""
    labels = {"user": "User", "assistant": "Assistant"}
    blocks = []
    for row in rows:
        if row["role"] not in labels or (row.get("status_code") or 200) != 200:
            continue
        content = row["content"]
        if len(content) > max_message_chars:
            content = content[:max_message_chars] + CUT_MARKER
        blocks.append(f"{labels[row['role']]}: {content}")
    return blocks


def model_window(top_provider: Optional[dict[str, Any]]) -> int:
    """Input tokens the model can take after reserving its completion tokens; 0 when it reports no usable window."""
    context_length = int((top_provider or {}).get("context_length") or 0)
    reserved = int((top_provider or {}).get("max_completion_tokens") or 0)
    return max(0, (context_length - reserved) * MARGIN_PERCENT // 100) if context_length > 0 else 0


def single_call_limit(single_call_max: int, top_provider: Optional[dict[str, Any]]) -> int:
    """Most tokens one call may carry: the cost cap, lowered to what the model reports. 0 means "no data"."""
    window = model_window(top_provider)
    return min(single_call_max, window) if window else 0


def effective_chunk_tokens(chunk_tokens: int, top_provider: Optional[dict[str, Any]]) -> int:
    """The fixed chunk size, lowered when the model reports a smaller usable window; never below 1."""
    window = model_window(top_provider)
    return max(1, min(chunk_tokens, window) if window else chunk_tokens)


def split_blocks(blocks: list[str], chunk_tokens: int) -> list[list[str]]:
    """Group blocks, in order, into chunks of at most `chunk_tokens`; a block is never split (a big one gets its own)."""
    chunks: list[list[str]] = []
    current: list[str] = []
    used = 0
    for block in blocks:
        tokens = estimate_tokens(block)
        if current and used + tokens > chunk_tokens:
            chunks.append(current)
            current, used = [], 0
        current.append(block)
        used += tokens
    if current:
        chunks.append(current)
    return chunks
