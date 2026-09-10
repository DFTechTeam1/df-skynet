from apps.secret import DB_SYNC_URL
from factory.alchemy import SQLAlchemyModelFactory
from services.mysql import make_sync_session
from factory.declarations import LazyFunction
from services.mysql.model.df_engine_image_generation_details import DfEngineImageGenerationDetails


class DfEngineImageGenerationDetailsFactory(SQLAlchemyModelFactory):
    class Meta:  # type: ignore
        model = DfEngineImageGenerationDetails
        sqlalchemy_session = make_sync_session(DB_SYNC_URL)
        sqlalchemy_session_persistence = "commit"

    id = None
    generation_id = None
    enhancer_id = None
    parameter = LazyFunction(dict)
    x_min = None
    x_max = None
    y_min = None
    y_max = None
