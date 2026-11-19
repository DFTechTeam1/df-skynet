import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Literal, TypedDict
import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ImageUrl, NativeOutput
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.providers.openrouter import OpenRouterProvider

from apps.secret import OPENROUTER_API_KEY


# ---------------------------------------------------------------------------
# 0. logging: every OpenRouter request + response (API key masked)
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),  # print to terminal
        logging.FileHandler("openrouter.log", encoding="utf-8"),  # and save to a file
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # hide httpx's own one-line request log

http_logger = logging.getLogger("openrouter.http")
run_logger = logging.getLogger("openrouter.run")

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}


def _mask_headers(headers: httpx.Headers) -> dict[str, str]:
    out = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADERS:
            out[k] = v[:16] + "..." + v[-4:] if len(v) > 20 else "***"
        else:
            out[k] = v
    return out


def _pretty(raw: bytes) -> str:
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except Exception:
        return raw.decode("utf-8", errors="replace")


async def _log_request(request: httpx.Request) -> None:
    request.extensions["start_time"] = time.perf_counter()
    http_logger.info(
        "REQUEST %s %s\nheaders: %s\nbody:\n%s",
        request.method,
        request.url,
        json.dumps(_mask_headers(request.headers), indent=2),
        _pretty(request.content),
    )


async def _log_response(response: httpx.Response) -> None:
    await response.aread()  # load the body so it can be logged (the client can still read it)
    start = response.request.extensions.get("start_time")
    elapsed = f"{(time.perf_counter() - start) * 1000:.0f} ms" if start else "?"
    http_logger.info(
        "RESPONSE %s %s (%s)\nheaders: %s\nbody:\n%s",
        response.status_code,
        response.request.url,
        elapsed,
        json.dumps(_mask_headers(response.headers), indent=2),
        _pretty(response.content),
    )


def make_logging_client(timeout: float = 120, **kwargs) -> httpx.AsyncClient:
    """httpx client that logs every request and response."""
    return httpx.AsyncClient(
        timeout=timeout,
        event_hooks={"request": [_log_request], "response": [_log_response]},
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. response_format  ->  Pydantic output model
#    Field descriptions become the JSON-schema descriptions the model reads.
#    No defaults on purpose: strict mode needs every field in "required".
# ---------------------------------------------------------------------------

CONTENT_RULES = (
    "The full reply shown to the user, written in Markdown with these fixed rules. "
    "LANGUAGE: reply in the same language the user wrote in. "
    "PARAGRAPHS: separate paragraphs with a blank line (\\n\\n). Never merge sentences from different "
    "paragraphs or list items onto one line. "
    "LISTS: each list item on its own line. Use '1. ' for steps or questions the user must answer, "
    "'- ' for unordered points. Put \\n between items and \\n\\n before and after the list. "
    "EMPHASIS: use **bold** only for key terms or labels (e.g. **Surface:**). No italics, no headings (#), "
    "no tables, no HTML tags. "
    "CODE / PROMPT BLOCKS: any structured data, prompt, JSON, or code goes inside plain ``` fences with NO "
    "language tag (write ``` not ```json), with \\n\\n before the opening fence, \\n after the opening fence "
    "and \\n before the closing fence. Never output structured data outside a fence. "
    "GENERATION PROMPT: when has_generation_prompt is true, content MUST contain exactly ONE fenced block "
    "holding ONLY the final generation prompt (no other text inside the fence), written in English, following "
    "the project skeleton one block per line (SCENE, DEPTH LAYERS, COMPOSITION, LIGHTING, COLOR, OPTICS, "
    "ATMOSPHERE, ORIENTATION), built from the whole conversation context, with no uids, URLs or <refer> tags "
    "inside the fence. Before the fence, list any assumptions you made. When has_generation_prompt is false, "
    "do not write a generation prompt. "
    "ATTACHMENTS: refer to an image / video / file only with the exact tag <refer to {uid}>, using the uid "
    "exactly as given. Never paste raw URLs into content. "
    "QUESTIONS: when information is missing, ask in a numbered list, one question per item, each starting "
    "with a **bold label:**. "
    "STRUCTURE ORDER: (1) short intro sentence, (2) body paragraphs or list, (3) optional fenced block, "
    "(4) optional one-line closing. Do not add text after the closing fence except one short closing line."
)


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")  # -> "additionalProperties": false

    uid: str = Field(
        description="Exact uid as given in the conversation's [uid=... url=... source=...] marker. "
        "Never invent or modify."
    )
    source: Literal["upload", "generated", "element"] = Field(
        description="Copy from the source= value in the attachment marker. upload = user-uploaded image, "
        "generated = image-generation output, element = project element."
    )
    url: str = Field(
        description="Copy character-for-character from the url= value in the attachment marker, "
        "including percent-encoding. Never shorten or re-encode."
    )


REPLY_DESCRIPTION = (
    "Every reply MUST follow the same formatting rules below, regardless of topic "
    "(greeting, question, image analysis, clarification, or generation prompt)."
)


class ChatReply(BaseModel):
    model_config = ConfigDict(extra="forbid")  # -> "additionalProperties": false

    content: str = Field(description=CONTENT_RULES)
    attachments: list[Attachment] = Field(
        description="One entry per attachment referenced with <refer to {uid}> in content, in order of "
        "FIRST appearance in content. No duplicates. Must match the <refer> tags exactly: no extra entries, "
        "none missing. Empty array [] if content has no <refer> tag."
    )
    has_generation_prompt: bool = Field(
        description="Default false. Set true ONLY when the user asks to generate / create / render / make an "
        "image, video or other media (or asks for a prompt to do so) AND this reply contains the final "
        "generation prompt in a fenced block. The prompt must use the WHOLE conversation context: every "
        "earlier request, referenced attachment, stated preference, previous prompt draft and the user's "
        "corrections. When the user adjusts a previous prompt (e.g. 'make it warmer'), write the full updated "
        "prompt again and set true. Set false for everything else: greetings, questions, image analysis, "
        "opinions, and replies that only ask the user for missing information."
    )


# ---------------------------------------------------------------------------
# 2. system message  ->  instructions (base text + .md files)
# ---------------------------------------------------------------------------

BASE_INSTRUCTIONS = "You are an assistant that helps on project Maria Theressa. Your task is to assist user needs."


BASE_DIR = Path(__file__).resolve().parent


def build_instructions(doc_paths: list[str]) -> str:
    """Base text plus each .md file wrapped in a named <document> tag. Keep the order fixed for caching."""
    parts = [BASE_INSTRUCTIONS]
    for p in doc_paths:
        path = BASE_DIR / p
        if not path.is_file():
            raise FileNotFoundError(f"Instruction doc not found: {path}")
        text = path.read_text(encoding="utf-8").strip()
        parts.append(f'<document name="{path.name}">\n{text}\n</document>')
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 3. model + agent  (model, temperature, response_format)
# ---------------------------------------------------------------------------


def build_agent(doc_paths: list[str], model_name: str = "google/gemini-2.5-flash") -> Agent[None, ChatReply]:
    model = OpenRouterModel(
        model_name,
        provider=OpenRouterProvider(api_key="tes", http_client=make_logging_client()),
    )
    return Agent(
        model,
        # NativeOutput = OpenRouter response_format json_schema (same as your payload).
        # Without it, Pydantic AI asks for the JSON through a tool call instead.
        output_type=NativeOutput(ChatReply, name="chat_reply", description=REPLY_DESCRIPTION, strict=True),
        instructions=build_instructions(doc_paths),
        model_settings=OpenRouterModelSettings(temperature=0),
    )


# ---------------------------------------------------------------------------
# 4. messages  ->  message_history
# ---------------------------------------------------------------------------


class AttachmentRef(TypedDict):
    uid: str
    url: str
    source: str


class Turn(TypedDict):
    role: Literal["user", "assistant"]
    text: str
    attachments: list[AttachmentRef]


def marker(a: AttachmentRef) -> str:
    return f"[uid={a['uid']} url={a['url']} source={a['source']}]"


def user_content(text: str, attachments: list[AttachmentRef]) -> list[str | ImageUrl]:
    """User turn: text, then marker + image for each attachment (same as your payload)."""
    content: list[str | ImageUrl] = [text]
    for a in attachments:
        content.append(marker(a))
        content.append(ImageUrl(url=a["url"]))
    return content


def to_message_history(turns: list[Turn]) -> list[ModelMessage]:
    history: list[ModelMessage] = []
    for t in turns:
        if t["role"] == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=user_content(t["text"], t["attachments"]))]))
        else:
            # Pydantic AI assistant turns hold text only, so the markers go in as text and the
            # images are not re-sent (they are already in the user turns).
            text = "\n\n".join([t["text"], *(marker(a) for a in t["attachments"])])
            print("ini brooo", text)
            history.append(ModelResponse(parts=[TextPart(content=text)]))
    return history


# ---------------------------------------------------------------------------
# 5. one chat turn
# ---------------------------------------------------------------------------


async def chat(
    agent: Agent[None, ChatReply],
    turns: list[Turn],
    user_text: str,
    user_attachments: list[AttachmentRef] | None = None,
) -> ChatReply:
    result = await agent.run(
        user_content(user_text, user_attachments or []),
        message_history=to_message_history(turns),
    )
    run_logger.info(
        "usage: %s\nmessages:\n%s",
        result.usage(),
        json.dumps(json.loads(result.all_messages_json()), indent=2, ensure_ascii=False),
    )
    return result.output  # a validated ChatReply, no json.loads needed


IMG_1 = {
    "uid": "3f2a9c1e-8b4d-4e7a-9f1c-2d5e6a7b8c90",
    "url": "https://local-tunnel.dfactory.pro/storage/DF-Engine-DEV/Engagement%20of%20Imelda%20&%20Alex_ac0f2698/upload/images/2017_12_03_Borobudur%20(9)_7d4c4f.png",
    "source": "upload",
}
IMG_2 = {
    "uid": "a7c4e2f1-1d3b-4c5e-8a9f-0b1c2d3e4f56",
    "url": "https://local-tunnel.dfactory.pro/storage/DF-Engine-DEV/FEO%20Dinner%20&%20Dance%202026_15406fa0/upload/images/WhatsApp%20Image%202026-11-10%20at%2016.38.53_ea1997.jpeg",
    "source": "upload",
}

turns: list[Turn] = [
    {"role": "user", "text": "Hellooo", "attachments": []},
    {
        "role": "assistant",
        "text": "Hello! I am the assistant for project Maria Theressa. How can I help you today?",
        "attachments": [],
    },
    {
        "role": "user",
        "text": f"based on this image @{IMG_1['uid']} and this image @{IMG_2['uid']}, what do they mean?",
        "attachments": [IMG_1, IMG_2],
    },
]


if __name__ == "__main__":
    print(build_instructions(["docs/formulas/image-led-fullgen.md"]))
    # agent = build_agent(["docs/formulas/image-led-fullgen.md"])
    # reply = asyncio.run(chat(
    #     agent, turns,
    #     "maqntap! generatin prompt lagi dong, yang lebih pendek tapi yah jangan lupa referensinya juga dong",
    # ))
    # print(reply.content)
    # print(reply.attachments)
    # print(reply.has_generation_prompt)
