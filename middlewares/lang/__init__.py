from middlewares.lang.en.auth import AuthMessage as _EnAuth
from middlewares.lang.en.common import CommonMessage as _EnCommon
from middlewares.lang.en.equipment import EquipmentMessage as _EnEquipment
from middlewares.lang.en.prompt_template import (
    PromptTemplateMessage as _EnPromptTemplate,
)
from middlewares.lang.id.auth import AuthMessage as _IdAuth
from middlewares.lang.id.common import CommonMessage as _IdCommon
from middlewares.lang.id.equipment import EquipmentMessage as _IdEquipment
from middlewares.lang.id.prompt_template import (
    PromptTemplateMessage as _IdPromptTemplate,
)

DEFAULT_LANG = "en"
SUPPORTED_LANGUAGES = {"id", "en"}

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        **_EnAuth().message,
        **_EnCommon().message,
        **_EnEquipment().message,
        **_EnPromptTemplate().message,
    },
    "id": {
        **_IdAuth().message,
        **_IdCommon().message,
        **_IdEquipment().message,
        **_IdPromptTemplate().message,
    },
}


def resolve_message(key: str, lang: str = DEFAULT_LANG) -> str:
    """Translate a message key using `lang`, falling back to English, then the raw key."""
    localized = MESSAGES.get(lang, MESSAGES[DEFAULT_LANG])
    return localized.get(key, MESSAGES[DEFAULT_LANG].get(key, key))
