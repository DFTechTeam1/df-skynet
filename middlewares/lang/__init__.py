from contextvars import ContextVar
from middlewares.lang.en.auth import AuthMessage as _EnAuth
from middlewares.lang.en.common import CommonMessage as _EnCommon
from middlewares.lang.en.equipment import EquipmentMessage as _EnEquipment
from middlewares.lang.en.feature_management import (
    FeatureManagementMessage as _EnFeatureManagement,
)
from middlewares.lang.en.api_key_management import ApiKeyManagementMessage as _EnKeyManagement
from middlewares.lang.en.menu_management import (
    MenuManagementMessage as _EnMenuManagement,
)
from middlewares.lang.en.model_management import ModelManagementMessage as _EnModelManagement
from middlewares.lang.en.prompt_template import (
    PromptTemplateMessage as _EnPromptTemplate,
)
from middlewares.lang.en.setting import SettingMessage as _EnSetting
from middlewares.lang.id.auth import AuthMessage as _IdAuth
from middlewares.lang.id.common import CommonMessage as _IdCommon
from middlewares.lang.id.equipment import EquipmentMessage as _IdEquipment
from middlewares.lang.id.feature_management import (
    FeatureManagementMessage as _IdFeatureManagement,
)
from middlewares.lang.id.api_key_management import ApiKeyManagementMessage as _IdKeyManagement
from middlewares.lang.id.menu_management import (
    MenuManagementMessage as _IdMenuManagement,
)
from middlewares.lang.id.model_management import ModelManagementMessage as _IdModelManagement
from middlewares.lang.id.prompt_template import (
    PromptTemplateMessage as _IdPromptTemplate,
)
from middlewares.lang.id.setting import SettingMessage as _IdSetting

DEFAULT_LANG = "en"
SUPPORTED_LANGUAGES = {"id", "en"}
current_lang: ContextVar[str] = ContextVar("current_lang", default=DEFAULT_LANG)

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        **_EnAuth().message,
        **_EnCommon().message,
        **_EnEquipment().message,
        **_EnFeatureManagement().message,
        **_EnKeyManagement().message,
        **_EnMenuManagement().message,
        **_EnModelManagement().message,
        **_EnPromptTemplate().message,
        **_EnSetting().message,
    },
    "id": {
        **_IdAuth().message,
        **_IdCommon().message,
        **_IdEquipment().message,
        **_IdFeatureManagement().message,
        **_IdKeyManagement().message,
        **_IdMenuManagement().message,
        **_IdModelManagement().message,
        **_IdPromptTemplate().message,
        **_IdSetting().message,
    },
}


def resolve_message(key: str, lang: str = DEFAULT_LANG) -> str:
    """Translate a message key using `lang`, falling back to English, then the raw key."""
    localized = MESSAGES.get(lang, MESSAGES[DEFAULT_LANG])
    return localized.get(key, MESSAGES[DEFAULT_LANG].get(key, key))
