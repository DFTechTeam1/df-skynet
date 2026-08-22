import traceback
from typing import Any, Optional
from uuid import uuid4, UUID
from fastapi import status, Depends, Path, Query
from fastapi_controller import controller
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.menu_management import MenuPayload
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    Users,
    Employees,
)
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils.serializer import serialize
from utils.formatter import format_datetime, format_user_employees
# from apps.dependency.permission import require_permissions

from enum import StrEnum, auto


class ModelUsageTypes(StrEnum):
    text = auto()
    image = auto()
    video = auto()


model_management_permission = {
    "fetch_df_engine_model_option": "fetch_df_engine_model_option",
    "sync_df_engine_option": "sync_df_engine_option",
}


class ModelManagementController(CoreDependencies):
    @controller.get(
        "/models",
        summary="create propper user friendly summary",
        description="create propper user friendly descption",
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_df_engine_model_option"])) # Will be enabled later
        # ]
    )
    async def model_management_to_fetch_available_models(
        self, type: Optional[ModelUsageTypes] = Query(None)
    ) -> Response:
        response = Response()
        try:
            pass
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.post(
        "/models",
        summary="create propper user friendly summary",
        description="create propper user friendly descption",
        status_code=status.HTTP_200_OK,
        tags=["Model Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_df_engine_model_option"])) # Will be enabled later
        # ]
    )
    async def model_management_to_sync_available_models(self) -> Response:
        response = Response()
        try:
            pass
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
