from datetime import datetime
from enum import StrEnum, auto
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class LimitResetEnum(StrEnum):
    daily = auto()
    weekly = auto()
    monthly = auto()


class ApiKeyBasePayload(BaseModel):
    """Fields shared by create and update — everything except `expires_at`,
    which only create supports (see `ApiKeyPayload`/`ApiKeyUpdatePayload`).
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


class ApiKeyPayload(ApiKeyBasePayload):
    """Payload to create an API key. Includes `expires_at` since OpenRouter's
    create endpoint (`POST /keys`) accepts it.
    """

    expires_at: Optional[datetime] = Field(
        default=None,
        description="When this key expires.",
        examples=["2027-12-31 23:59:59"],
    )

    @property
    def expires_at_iso(self) -> Optional[str]:
        return f"{self.expires_at.isoformat()}Z" if self.expires_at else None


class ApiKeyUpdatePayload(ApiKeyBasePayload):
    """Payload to fully replace an API key's editable fields — no
    `expires_at`. OpenRouter's update endpoint (`PATCH /keys/{hash}`) has no
    way to change a key's expiry after creation, so it isn't editable here.
    """
