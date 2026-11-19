from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal


class ChatAttachment(BaseModel):
    """
    source.upload: data comes from df_engine_upload_files with type of image
    source.generated: data comes from df_engine_generation_results with generaion type in image or image_edit
    source.element: for future use, this will mapped from elements table
    """

    model_config = ConfigDict(extra="forbid")

    uid: str = Field(
        ...,
        description="Exact uid as given in the conversation's [uid=... url=... source=...] marker. Never invent or modify.",
    )
    source: Literal["upload", "generated", "element"] = Field(
        ...,
        description=(
            "Copy from the source= value in the attachment marker. "
            "upload = user-uploaded image, generated = image-generation output, element = project element."
        ),
    )
    url: str = Field(
        ...,
        description=(
            "Copy character-for-character from the url= value in the attachment marker, including percent-encoding. "
            "Never shorten or re-encode."
        ),
    )

    def marker(self) -> str:
        return f"[uid={self.uid} url={self.url} source={self.source}]"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"] = Field(...)
    text: str = Field(...)
    attachments: list[ChatAttachment] = Field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": self.text}]
        for a in self.attachments:
            content.append({"type": "text", "text": a.marker()})
            content.append({"type": "image_url", "image_url": {"url": a.url}})
        return {"role": self.role, "content": content}


class LLMResponse(BaseModel):
    """Every reply MUST follow the same formatting rules below, regardless of topic (greeting, question, image analysis, clarification, or generation prompt)."""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(
        ...,
        description=(
            "The full reply shown to the user, written in Markdown with these fixed rules. "
            "LANGUAGE: reply in the same language the user wrote in. "
            "PARAGRAPHS: separate paragraphs with a blank line (\\n\\n). Never merge sentences from different paragraphs or list items onto one line. "
            "LISTS: each list item on its own line. Use '1. ' for steps or questions the user must answer, '- ' for unordered points. Put \\n between items and \\n\\n before and after the list. "
            "EMPHASIS: use **bold** only for key terms or labels (e.g. **Surface:**). No italics, no headings (#), no tables, no HTML tags. "
            "CODE / PROMPT BLOCKS: any structured data, prompt, JSON, or code goes inside plain ``` fences with NO language tag (write ``` not ```json), "
            "with \\n\\n before the opening fence, \\n after the opening fence and \\n before the closing fence. Never output structured data outside a fence. "
            "GENERATION PROMPT: when has_generation_prompt is true, content MUST contain exactly ONE fenced block holding ONLY the final generation prompt "
            "(no other text inside the fence), written in English, following the project skeleton one block per line "
            "(SCENE, DEPTH LAYERS, COMPOSITION, LIGHTING, COLOR, OPTICS, ATMOSPHERE, ORIENTATION), built from the whole conversation context, "
            "with no uids, URLs or <refer> tags inside the fence. Before the fence, list any assumptions you made. "
            "When has_generation_prompt is false, do not write a generation prompt. "
            "ATTACHMENTS: refer to an image / video / file only with the exact tag <refer to {uid}>, using the uid exactly as given. "
            "The tag MUST end with the closing '>' character, e.g. <refer to 3f2a9c1e-8b4d-4e7a-9f1c-2d5e6a7b8c90> (never <refer to 3f2a9c1e-... without '>'). "
            "Never write @uid or a bare uid, never paste raw URLs into content. "
            "QUESTIONS: when information is missing, ask in a numbered list, one question per item, each starting with a **bold label:**. "
            "STRUCTURE ORDER: (1) short intro sentence, (2) body paragraphs or list, (3) optional fenced block, (4) optional one-line closing. "
            "Do not add text after the closing fence except one short closing line."
        ),
    )
    attachments: list["ChatAttachment"] = Field(
        ...,
        description=(
            "One entry per attachment referenced with <refer to {uid}> in content, in order of FIRST appearance in content. "
            "No duplicates. Must match the <refer> tags exactly: no extra entries, none missing. "
            "Empty array [] if content has no <refer> tag."
        ),
    )
    has_generation_prompt: bool = Field(
        ...,
        description=(
            "Default false. Set true ONLY when the user asks to generate / create / render / make an image, video or other media "
            "(or asks for a prompt to do so) AND this reply contains the final generation prompt in a fenced block. "
            "The prompt must use the WHOLE conversation context: every earlier request, referenced attachment, stated preference, "
            "previous prompt draft and the user's corrections. When the user adjusts a previous prompt (e.g. 'make it warmer'), "
            "write the full updated prompt again and set true. Set false for everything else: greetings, questions, image analysis, "
            "opinions, and replies that only ask the user for missing information."
        ),
    )

    @classmethod
    def response_format(cls, name: str = "chat_reply") -> dict:
        return {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": cls.model_json_schema()},
        }
