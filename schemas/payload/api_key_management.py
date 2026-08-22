from datetime import datetime
from enum import StrEnum, auto
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from utils import wib_to_utc_iso


class LimitResetEnum(StrEnum):
    daily = auto()
    weekly = auto()
    monthly = auto()


class CreateApiKeyPayload(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique, human-readable name identifying this API key.",
        examples=["Production · Video"],
    )
    description: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Free-text explanation of what this key is used for.",
        examples=["Used for production video generation jobs."],
    )
    employee_uid: UUID = Field(
        ...,
        description="PIC (person in charge) — resolved server-side to employees.id via employees.uid.",
        examples=["df4a895e-d915-4c01-b687-a03fffa6919a"],
    )
    limit: Optional[float] = Field(
        default=None,
        ge=0,
        description="Usage limit in USD for this key, reset on the `limit_reset` cadence.",
        examples=[50.00],
    )
    limit_reset: Optional[LimitResetEnum] = Field(
        default=None,
        description="How often `limit_usage` resets.",
        examples=["monthly"],
    )
    is_main: bool = Field(
        default=True,
        description="Whether this key can currently be used for generation.",
        examples=[True],
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="When this key expires, as WIB (Asia/Jakarta) wall-clock time.",
        examples=["2027-12-31 23:59:59"],
    )

    @property
    def expires_at_iso(self) -> Optional[str]:
        """`expires_at` is entered as WIB; convert to UTC isoformat for OpenRouter."""
        return wib_to_utc_iso(self.expires_at)


class UpdateApiKeyPayload(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique, human-readable name identifying this API key.",
        examples=["Production · Video"],
    )
    description: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Free-text explanation of what this key is used for.",
        examples=["Used for production video generation jobs."],
    )
    limit: Optional[float] = Field(
        default=None,
        ge=0,
        description="Usage limit in USD for this key, reset on the `limit_reset` cadence.",
        examples=[50.00],
    )
    limit_reset: Optional[LimitResetEnum] = Field(
        default=None,
        description="How often `limit_usage` resets.",
        examples=["monthly"],
    )
    is_main: bool = Field(
        default=True,
        description="Whether this key can currently be used for generation.",
        examples=[True],
    )
