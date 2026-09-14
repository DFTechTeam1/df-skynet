import traceback
from fastapi import status, Query
from fastapi_controller import controller
from sqlalchemy import func
from apps.controller.core import CoreDependencies
from schemas.response import PaginationResponse, Response
from schemas.payload.api_logs import LogSourceEnum
from services.mysql import query
from services.mysql.model import DfEngineExternalApiCalls
from services.redis import get_json, set_json, CacheKeys
from services.api_logs import ApiLogsService
from log import logging
from error import ServiceError, BaseError
from utils.serializer import serialize


class ApiLogsController(CoreDependencies):
    @controller.get(
        "/logs",
        summary="View the call log of an external integration.",
        description=(
            "Returns the call history for one integration, newest first: every time "
            "this service contacted it, this records who triggered it (where "
            "applicable), the HTTP method and endpoint, the request payload, response "
            "status code, response headers and body, how long the call took, and any "
            "error. Request headers are left out because they can carry a credential. "
            "Paginated — pass `page` and `itemsPerPage` to page through the history."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Logs"],
        response_model=Response,
    )
    async def api_logs_to_fetch(
        self,
        source: LogSourceEnum = Query(LogSourceEnum.openrouter, description="Which integration's call log to return."),
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        api_logs_service = ApiLogsService()
        try:
            logs_cache_key = cache_key.api_logs(source.value, page, itemsPerPage)
            cached = await get_json(self.redis, logs_cache_key)
            if cached is not None:
                logging.info(
                    f"user={self.user['user_id']} returned {source.value} call log page {page} "
                    f"({len(cached['logs'])} row(s)) from cache"
                )
                response.data = PaginationResponse(paginated=cached["logs"], totalData=cached["total_data"])
                return response

            filters = (DfEngineExternalApiCalls.type == source.value,)  # type: ignore

            total_data = (
                await query(
                    db=self.db,
                    table=DfEngineExternalApiCalls,
                    columns=(func.count(DfEngineExternalApiCalls.id),),  # type: ignore
                    filters=filters,
                    fetch_one=True,
                )
                or 0
            )

            records = await query(
                db=self.db,
                table=DfEngineExternalApiCalls,
                filters=filters,
                order_by=(DfEngineExternalApiCalls.created_at.desc(), DfEngineExternalApiCalls.id.desc()),  # type: ignore
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
            )

            logs = [api_logs_service.format_log(record, source.value) for record in serialize(records)]

            await set_json(self.redis, logs_cache_key, {"logs": logs, "total_data": total_data})
            logging.info(
                f"user={self.user['user_id']} returned {source.value} call log page {page} "
                f"({len(logs)} of {total_data} row(s)) from database"
            )
            response.data = PaginationResponse(paginated=logs, totalData=total_data)
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not return {source.value} call log (page {page}): "
                f"{e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error returning {source.value} call log\n"
                f"{traceback.format_exc()}"
            )
            raise ServiceError()
        return response
