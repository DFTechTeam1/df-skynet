from enum import Enum
from pydantic import BaseModel, Field


class ThemeEnum(str, Enum):
    DARK = "dark"
    LIGHT = "light"


class AccentEnum(str, Enum):
    SIGNAL = "signal"
    VIOLET = "violet"
    TEAL = "teal"


class LanguageEnum(str, Enum):
    INDONESIA = "indonesia"
    ENGLISH = "english"


class AspectRatioEnum(str, Enum):
    RATIO_16_9 = "16:9"
    RATIO_1_1 = "1:1"
    RATIO_9_16 = "9:16"
    RATIO_4_3 = "4:3"
    RATIO_3_4 = "3:4"


class SizeEnum(str, Enum):
    ONE_K = "1K"
    TWO_K = "2K"
    FOUR_K = "4K"


class ConfirmBeforeSpendingEnum(str, Enum):
    OVER_0_5 = "over_0.5"
    OFF = "off"
    OVER_0_1 = "over_0.1"
    ALWAYS = "always"


CONFIRM_BEFORE_SPENDING_LABELS: dict[str, str] = {
    ConfirmBeforeSpendingEnum.OVER_0_5.value: "Over 0.5",
    ConfirmBeforeSpendingEnum.OFF.value: "Off",
    ConfirmBeforeSpendingEnum.OVER_0_1.value: "Over 0.1",
    ConfirmBeforeSpendingEnum.ALWAYS.value: "Always",
}


class PreferencePayload(BaseModel):
    """Payload to create or fully replace the current user's preferences.

    Used for both first save and update — PUT replaces the full record, not
    a partial diff. Every field has a sensible default, so a partial-looking
    request still resolves to a complete, valid preference set.
    """

    theme: ThemeEnum = Field(default=ThemeEnum.DARK, description="Switches the whole app live.")
    accent: AccentEnum = Field(default=AccentEnum.TEAL, description="Signal, Violet or Teal — applied live.")
    language: LanguageEnum = Field(default=LanguageEnum.ENGLISH, description="Interface language.")
    default_aspect_ratio: AspectRatioEnum = Field(
        default=AspectRatioEnum.RATIO_16_9, description="New generations start with this ratio."
    )
    default_size: SizeEnum = Field(default=SizeEnum.FOUR_K, description="Default output resolution.")
    confirm_before_spending: ConfirmBeforeSpendingEnum = Field(
        default=ConfirmBeforeSpendingEnum.OVER_0_5,
        description="Ask before any generation that costs more than this.",
        examples=["over_0.5"],
    )
