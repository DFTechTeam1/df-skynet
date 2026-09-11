from uuid import uuid4
from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_scene_shots import (
    DfEngineSceneShots,
    InteriorStyles,
    LightingMoods,
    TimeOfDays,
)
from utils import local_time


class DfEngineSceneShotsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineSceneShots
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    created_at = LazyFunction(local_time)
    updated_at = None
    archieved_at = None
    scene_id = None
    name = LazyFunction(lambda: f"Shot {uuid4().hex[:8]}")
    interior_style = InteriorStyles.interior
    time_of_day = TimeOfDays.sunrise
    lighting_mood = LightingMoods.natural
