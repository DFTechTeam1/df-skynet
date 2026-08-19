from fastapi import status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi_controller import controller
from scalar_fastapi import get_scalar_api_reference
from apps.controller.core import PlainDependencies
from utils import get_project_root
from error import ServiceError


class CommonController(PlainDependencies):
    @controller.get(
        "/",
        summary="Root.",
        status_code=status.HTTP_200_OK,
        tags=["Common"],
    )
    async def restricted_page(self) -> FileResponse:
        RESTRICTED_PAGE = get_project_root() / "static" / "restricted.html"
        return FileResponse(RESTRICTED_PAGE)

    @controller.get(
        "/docs",
        summary="Scalar OpenAPI.",
        status_code=status.HTTP_200_OK,
        tags=["Common"],
    )
    async def scalar_docs(self) -> HTMLResponse:
        return get_scalar_api_reference(openapi_url="/openapi.json")
