import traceback
from fastapi import status
from fastapi_controller import controller
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.user_preference import PreferencePayload, CONFIRM_BEFORE_SPENDING_LABELS
from services.mysql import query
from utils.serializer import serialize
from services.mysql.model import DfEnginePreferences
from services.redis import get_json, set_json, CacheKeys
from log import logging
from error import ServiceError, BaseError
from utils import local_time


class UserPreferenceController(CoreDependencies):
    @controller.get(
        "/user-preference",
        summary="Fetch the current user's preferences.",
        description=(
            "Returns the authenticated user's saved preferences (theme, accent, language, "
            "default aspect ratio, default size, confirm-before-spending threshold). If the "
            "user has never saved preferences yet, returns the default values without "
            "creating a row. The resolved result is cached per user id, so repeat fetches "
            "skip the DB even for users still on the defaults."
        ),
        status_code=status.HTTP_200_OK,
        tags=["User Preference"],
        response_model=Response,
    )
    async def user_preferences_to_fetch_user_preference(self) -> Response:
        response = Response()
        try:
            user_id = int(self.user["user_id"])
            cache_key = CacheKeys().user_preference(user_id)

            cached = await get_json(self.redis, cache_key)
            if cached is not None:
                logging.info(f"user={user_id} fetched user preference source=cache")
                response.data = cached
                return response

            record = await query(
                db=self.db,
                table=DfEnginePreferences,
                filters=(DfEnginePreferences.user_id == user_id,),  # type: ignore
                fetch_one=True,
            )
            if record:
                record = serialize(record)
                record.pop("id", None)
                record.pop("user_id", None)
                record.pop("created_at", None)
                record.pop("updated_at", None)
                logging.info(f"user={user_id} fetched user preference source=db")
            else:
                record = PreferencePayload().model_dump(mode="json")
                logging.info(f"user={user_id} fetched user preference source=default")

            record["confirm_before_spending"] = CONFIRM_BEFORE_SPENDING_LABELS[record["confirm_before_spending"]]
            await set_json(self.redis, cache_key, record)
            response.data = record
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/user-preference",
        summary="Create or update the current user's preferences.",
        description=(
            "Replaces the authenticated user's preferences with the full payload given — "
            "inserts a new row if the user has none yet, otherwise updates the existing "
            "one. Not a partial diff: every field must be supplied, though each has a "
            "sensible default. The freshly saved value is written straight into the "
            "per-user cache, so an immediate fetch reflects it without a DB round-trip."
        ),
        status_code=status.HTTP_200_OK,
        tags=["User Preference"],
        response_model=Response,
    )
    async def user_preferences_to_update_user_preference(self, schema: PreferencePayload) -> Response:
        response = Response()
        try:
            user_id = int(self.user["user_id"])
            values = schema.model_dump(mode="json")

            row = await query(
                db=self.db,
                table=DfEnginePreferences,
                filters=(DfEnginePreferences.user_id == user_id,),  # type: ignore
                fetch_one=True,
            )
            if row:
                for field, value in values.items():
                    setattr(row, field, value)
                row.updated_at = local_time()
                action = "updated"
            else:
                row = DfEnginePreferences(user_id=user_id, **values)
                self.db.add(row)
                action = "created"

            await self.db.flush()

            logging.info(f"user={user_id} {action} user preference theme={row.theme!r} accent={row.accent!r}")

            record = serialize(row)
            record.pop("id", None)
            record.pop("user_id", None)
            record.pop("created_at", None)
            record.pop("updated_at", None)
            record["confirm_before_spending"] = CONFIRM_BEFORE_SPENDING_LABELS[record["confirm_before_spending"]]
            await set_json(self.redis, CacheKeys().user_preference(user_id), record)
            response.data = record
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
