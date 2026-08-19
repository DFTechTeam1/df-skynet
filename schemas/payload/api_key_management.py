from datetime import datetime, timezone
from enum import StrEnum, auto
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class LimitResetEnum(StrEnum):
    daily = auto()
    weekly = auto()
    monthly = auto()


class ApiKeyPayload(BaseModel):
    """Payload to create or fully replace an API key.

    Used for both create and update — PATCH replaces the full record, not a
    partial diff, matching the feature-management/prompt-template convention.
    `employee_uid` addresses the PIC via `employees.uid`; the controller
    resolves it to `employee_id` server-side.
    """

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
    api_key: str = Field(
        ...,
        min_length=1,
        description="The raw API key value (e.g. an OpenRouter key).",
        examples=["sk-or-v1-1234567890abcdef1234567890abcdef"],
    )
    employee_uid: UUID = Field(
        ...,
        description="PIC (person in charge) — resolved server-side to employees.id via employees.uid.",
        examples=["df4a895e-d915-4c01-b687-a03fffa6919a"],
    )
    limit_usage: Optional[float] = Field(
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
    expired_at: Optional[datetime] = Field(
        default=None,
        description="When this key expires.",
        examples=["2027-12-31T23:59:59Z"],
    )
    is_active: bool = Field(
        default=True,
        description="Whether this key can currently be used for generation.",
        examples=[True],
    )

    @field_validator("expired_at")
    @classmethod
    def normalize_expired_at(cls, value: Optional[datetime]) -> Optional[datetime]:
        """The `expired_at` column is a naive DateTime, but the documented
        input format uses a "Z" (UTC) suffix — so any tz-aware value is
        converted to naive UTC before it hits the DB, regardless of which
        offset the caller actually sent.
        """
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
