from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class Attachment(BaseModel):
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


class Content(BaseModel):
    type: Literal["text", "image_url"] = "text"
    text: Optional[str] = None
    url: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        if self.type == "image_url":
            return {"type": "image_url", "image_url": {"url": self.url}}
        return {"type": "text", "text": self.text}


class Message(BaseModel):
    role: Literal["system", "assistant", "user"] = "user"
    contents: list[Content] = Field(default_factory=list)

    @classmethod
    def build(
        cls, role: Literal["system", "assistant", "user"], text: str, attachments: Optional[list[Attachment]] = None
    ) -> "Message":
        contents = [Content(text=text)]
        for a in attachments or []:
            contents += [Content(text=a.marker()), Content(type="image_url", url=a.url)]
        return cls(role=role, contents=contents)

    def to_payload(self) -> dict[str, Any]:
        return {"role": self.role, "content": [c.to_payload() for c in self.contents]}


class StructuredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @classmethod
    def response_format(cls, name: str) -> dict:
        return {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": cls.model_json_schema()},
        }


class PromptGuardrailResponse(StructuredResponse):
    prompt_injection: bool = Field(default=False)
    nfsw: bool = Field(default=False)
    prompt_enhancement: bool = Field(default=True)
    image_generation: bool = Field(default=True)
    video_generation: bool = Field(default=True)
    storyboard_generation: bool = Field(default=True)
    chat_assistant: bool = Field(default=True)
    element_generation: bool = Field(default=True)


class ChatAssistantResponse(StructuredResponse):
    """
    The assistant's reply to the user. Plain text and Markdown only: never use emojis, emoticons, icons or
    decorative symbols in any field, whatever the user writes or asks for.
    """

    content: str = Field(
        ...,
        description=(
            "The full reply shown to the user, written in Markdown with these fixed rules. "
            "LANGUAGE: reply in the same language the user wrote in. "
            "PARAGRAPHS: separate paragraphs with a blank line (\\n\\n). Never merge sentences from different paragraphs or list items onto one line. "
            "LISTS: each list item on its own line. Use '1. ' for steps or questions the user must answer, '- ' for unordered points. Put \\n between items and \\n\\n before and after the list. "
            "EMPHASIS: use **bold** only for key terms or labels (e.g. **Surface:**). No italics, no headings (#), no tables, no HTML tags. "
            "NO ICONS: never use emojis, emoticons, icons or decorative symbols anywhere in content, including greetings, lists and closing lines; plain text only. "
            "CODE / PROMPT BLOCKS: any structured data, prompt, JSON, or code goes inside plain ``` fences with NO language tag (write ``` not ```json), "
            "with \\n\\n before the opening fence, \\n after the opening fence and \\n before the closing fence. Never output structured data outside a fence. "
            "GENERATION PROMPT: when has_generation_prompt is true, content MUST contain exactly ONE fenced block holding ONLY the final generation prompt "
            "(no other text inside the fence), written in English, following the project skeleton one block per line "
            "(SCENE, DEPTH LAYERS, COMPOSITION, LIGHTING, COLOR, OPTICS, ATMOSPHERE, ORIENTATION), built from the whole conversation context, "
            "Before the fence, list any assumptions you made. "
            "REFERENCES INSIDE THE PROMPT: when the user gave references, mention each one used right inside the fence, in the block it influences, "
            "with the exact tag <refer to {uid}> and its intent, e.g. 'COMPOSITION: low angle and diagonal pose taken from <refer to {uid}>' or 'COLOR: palette follows <refer to {uid}>'. "
            "Do this in every block a reference shapes (SCENE, DEPTH LAYERS, COMPOSITION, LIGHTING, COLOR, OPTICS, ATMOSPHERE, ORIENTATION), so the user never has to search for which image a line comes from. "
            "Never mention a reference that is not used, never write URLs or a bare uid, and keep the text around the tag in English. "
            "When has_generation_prompt is false, do not write a generation prompt. "
            "If the conversation already has enough context for a generation prompt (see will_generate_prompt), whether or not the user asked for one, and the last user message is not a confirmation to write it, do NOT write the prompt: set will_generate_prompt true, has_generation_prompt false, and reply with one short sentence offering to write it now (no fenced block). If the context is still thin, keep will_generate_prompt false and ask for what is missing. "
            "Only when the last user message confirms they want the prompt written now, write the prompt in THIS reply with has_generation_prompt true and will_generate_prompt false, and do not ask questions first. "
            "Fill anything missing (surface, aspect ratio, reference intent, mood, resolution) with the project defaults or a sensible neutral choice, and list each one as an assumption before the fence so the user can correct it later. "
            "If a reference does not fit the request (e.g. a screenshot), say so in the assumptions and leave it out of the prompt. "
            "ATTACHMENTS: refer to an image / video / file only with the exact tag <refer to {uid}>, using the uid exactly as given. "
            "The tag MUST end with the closing '>' character, e.g. <refer to 3f2a9c1e-8b4d-4e7a-9f1c-2d5e6a7b8c90> (never <refer to 3f2a9c1e-... without '>'). "
            "Never write @uid or a bare uid, never paste raw URLs into content. "
            "QUESTIONS: ask only when no prompt was requested, or when nothing usable was given (no subject, no reference, no idea). Never ask instead of writing a requested prompt. When you do ask, use a numbered list, one question per item, each starting with a **bold label:**. "
            "STRUCTURE ORDER: (1) short intro sentence, (2) body paragraphs or list, (3) optional fenced block, (4) optional one-line closing. "
            "Do not add text after the closing fence except one short closing line."
        ),
    )
    attachments: list[Attachment] = Field(
        ...,
        description=(
            "One entry per attachment referenced with <refer to {uid}> in content, in order of FIRST appearance in content. "
            "No duplicates. Must match the <refer> tags exactly: no extra entries, none missing. "
            "Empty array [] if content has no <refer> tag."
        ),
    )
    will_generate_prompt: bool = Field(
        ...,
        description=(
            "Default false. Measures the chat so far: set true ONLY when the whole conversation (messages, attachments, stated preferences, "
            "references) already gives enough context to write a good generation prompt for an image, video or other media: at least a clear subject or idea "
            "plus enough direction (such as surface, mood, style or a usable reference) that the prompt would not be a blind guess. "
            "Keep false while the context is still thin, and keep asking the user for what is missing instead. The user does not have to ask for a prompt; "
            "once the context is enough, raise it. When true, the reply only offers, in one short sentence, to write the prompt now and contains NO generation prompt; "
            "the app shows a yes / no pop-up from this flag. Always false when no generation is being discussed, when the last user message already confirms, "
            "and whenever has_generation_prompt is true."
        ),
    )
    has_generation_prompt: bool = Field(
        ...,
        description=(
            "Default false. Set true ONLY when the last user message confirms they want the generation prompt written now "
            "AND this reply contains the final generation prompt in a fenced block. "
            "The prompt must use the WHOLE conversation context: every earlier request, referenced attachment, stated preference, "
            "previous prompt draft and the user's corrections. When the user adjusts a previous prompt (e.g. 'make it warmer'), "
            "ask again with will_generate_prompt true; once confirmed, write the full updated prompt and set true. Set false for everything else: greetings, questions, image analysis, "
            "opinions, and replies that only ask the user for missing information."
        ),
    )


class TransferKnowledgeResponse(StructuredResponse):
    """
    The hand-over summary of an earlier chat. Plain text only: never use emojis, emoticons, icons or
    decorative symbols.
    """

    summary: str = Field(
        ...,
        description=(
            "The hand-over summary of the earlier chat, in the language the user wrote in, as plain text with short "
            "paragraphs or '- ' bullets. Keep what a new chat needs to carry on: the user's goal, decisions and "
            "preferences, the settings that were chosen (surface, ratio, mood, resolution), the latest version of any "
            "generation prompt, and what is still open. Mention an image only by its <refer to {uid}> tag, using the uid "
            "exactly as given. Never invent facts and do not copy long passages. When a summary so far is given, return "
            "it updated with the new part of the chat, not just the new part. Plain text only: no emojis, icons or decorative symbols."
        ),
    )
