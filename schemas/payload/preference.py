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
    confirm_before_spending: float = Field(
        default=0.5,
        ge=0,
        description="Ask before any generation that costs more than this.",
        examples=[0.5],
    )
