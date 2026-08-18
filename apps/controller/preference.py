import traceback
from typing import Any, Optional
from fastapi import status
from fastapi_controller import controller
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.preference import PreferencePayload
from services.mysql.model import DfEnginePreferences
from log import logging
from error import ServiceError, BaseError, DataConflictError
from utils import local_time


class PreferenceController(CoreDependencies):
    async def get_preference_row(self, user_id: int) -> Optional[DfEnginePreferences]:
        return (
            await self.db.execute(select(DfEnginePreferences).where(DfEnginePreferences.user_id == user_id))  # type: ignore
        ).scalar_one_or_none()

    async def get_preference(self, user_id: int) -> dict[str, Any]:
        row = await self.get_preference_row(user_id)
        if row is None:
            return PreferencePayload().model_dump(mode="json")
        return PreferencePayload.model_validate(row, from_attributes=True).model_dump(mode="json")

    async def upsert_preference(self, user_id: int, schema: PreferencePayload) -> dict[str, Any]:
        row = await self.get_preference_row(user_id)
        values = schema.model_dump(mode="json")

        if row is None:
            row = DfEnginePreferences(user_id=user_id, **values)
            self.db.add(row)
        else:
            for field, value in values.items():
                setattr(row, field, value)
            row.updated_at = local_time()

        try:
            await self.db.flush()
        except IntegrityError:
            raise DataConflictError(message="preference_already_exists")

        return PreferencePayload.model_validate(row, from_attributes=True).model_dump(mode="json")

    @controller.get(
        "/api/preferences",
        summary="Fetch the current user's preferences.",
        description=(
            "Returns the authenticated user's saved preferences (theme, accent, language, "
            "default aspect ratio, default size, confirm-before-spending threshold). If the "
            "user has never saved preferences yet, returns the default values without "
            "creating a row."
        ),
        status_code=status.HTTP_200_OK,
        tags=["User Preference"],
        response_model=Response,
    )
    async def preferences_to_fetch_user_preference(self) -> Response:
        response = Response()
        try:
            response.data = await self.get_preference(int(self.user["user_id"]))
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/api/preferences",
        summary="Create or update the current user's preferences.",
        description=(
            "Replaces the authenticated user's preferences with the full payload given — "
            "inserts a new row if the user has none yet, otherwise updates the existing "
            "one. Not a partial diff: every field must be supplied, though each has a "
            "sensible default."
        ),
        status_code=status.HTTP_200_OK,
        tags=["User Preference"],
        response_model=Response,
    )
    async def preferences_to_update_user_preference(self, schema: PreferencePayload) -> Response:
        response = Response()
        try:
            response.data = await self.upsert_preference(int(self.user["user_id"]), schema)
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
