import time
from typing import Any, Literal, Optional
from httpx import AsyncBaseTransport, AsyncClient, Response
from services.mysql import get_db, query
from services.mysql.model import DfEngineExternalApiCalls, Employees
from log import logging


class APICaller:
    def __init__(
        self,
        verify: bool = True,
        timeout: float = 120,
        transport: Optional[AsyncBaseTransport] = None,
        base_url: str = "",
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.client = AsyncClient(
            verify=verify,
            timeout=timeout,
            transport=transport,
            base_url=base_url,
            headers=headers,
        )

    async def call(
        self,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
        url: str,
        raise_for_status: bool = True,
        **kwargs: Any,
    ) -> Response:
        response = await self.client.request(
            method=method,
            url=url,
            **kwargs,
        )

        if raise_for_status:
            response.raise_for_status()

        return response

    def stream(self, method: str, url: str, **kwargs: Any) -> Any:
        return self.client.stream(method, url, **kwargs)

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "APICaller":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def _logged_call(
        self,
        type: Literal["openrouter", "udin"],
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
        url: str,
        raise_for_status: bool,
        user_id: int,
        **kwargs: Any,
    ) -> Response:
        started_at = time.perf_counter()
        response = await self.call(method, url, raise_for_status=False, **kwargs)
        try:
            response_body = response.json() if response.content else None
        except ValueError:
            response_body = None
        duration_ms = int((time.perf_counter() - started_at) * 1000)

        request_headers = {**self.client.headers, **kwargs.get("headers", {})}
        if "Authorization" in request_headers:
            request_headers["Authorization"] = "Bearer ***"

        if response.is_error:
            error_message = response_body
            logging.error(
                f"{type} call failed method={method} url={url} status={response.status_code} duration_ms={duration_ms}"
            )
        else:
            error_message = None
            logging.info(
                f"{type} call succeeded method={method} url={url} status={response.status_code} duration_ms={duration_ms}"
            )

        async for db in get_db():
            employee = await query(db=db, table=Employees, filters=(Employees.user_id == user_id,), fetch_one=True)
            db.add(
                DfEngineExternalApiCalls(
                    name=employee.nickname if employee else None,
                    type=type,
                    method=method,
                    endpoint=str(response.request.url),
                    request_headers=request_headers or None,
                    request_payload=kwargs.get("json") or kwargs.get("data"),
                    response_status_code=response.status_code,
                    response_headers=dict(response.headers),
                    response_body=response_body,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
            )

        if raise_for_status:
            response.raise_for_status()

        return response

    async def openrouter(
        self,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
        url: str,
        user_id: int,
        raise_for_status: bool = False,
        **kwargs: Any,
    ) -> Response:
        """Call the OpenRouter API and record it as an `openrouter` row in
        `df_engine_external_api_calls` (request/response, status, duration).
        `user_id` resolves the calling employee's nickname for the log's `name`
        column. Defaults to `raise_for_status=False` so callers can inspect the
        (still-logged) error response instead of catching an exception."""
        return await self._logged_call("openrouter", method, url, raise_for_status, user_id, **kwargs)

    async def udin(
        self,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
        url: str,
        user_id: int,
        raise_for_status: bool = False,
        **kwargs: Any,
    ) -> Response:
        """Call the Udin API and record it as a `udin` row in
        `df_engine_external_api_calls` (request/response, status, duration).
        `user_id` resolves the calling employee's nickname for the log's `name`
        column. Defaults to `raise_for_status=False` so callers can inspect the
        (still-logged) error response instead of catching an exception."""
        return await self._logged_call("udin", method, url, raise_for_status, user_id, **kwargs)
