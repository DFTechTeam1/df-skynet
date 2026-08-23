from pydantic import BaseModel, Field


class SetModelEnabledPayload(BaseModel):
    """Payload to enable or disable a model (`df_engine_model_options` row).

    Disabling a model that currently holds `is_main` also clears that flag
    server-side — a disabled model can never stay main.
    """

    is_enabled: bool = Field(
        ...,
        description="Whether this model should be enabled (selectable) or disabled.",
        examples=[True],
    )
