import time
from typing import Any, Literal, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from apps.secret import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from log import logging
from services.api_caller import APICaller
from services.mysql import query
from services.mysql.model import DfEngineOpenrouterLogs, Employees
from utils.serializer import to_json_safe


async def call_openrouter(
    db: AsyncSession,
    user_id: int,
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
    path: str,
    headers: Optional[dict[str, str]] = None,
    base_url: str = OPENROUTER_BASE_URL,
    raise_for_status: bool = False,
    **kwargs: Any,
) -> Any:
    """Call OpenRouter and always log the attempt (success or failure) to
    DfEngineOpenrouterLogs with an explicit commit, so the log survives even
    if the caller's later DB work fails or rolls back within the same
    request. One shared implementation for every controller that talks to
    OpenRouter, instead of each one carrying its own copy.

    `headers`/`base_url` default to the standard OpenRouter key/host but can
    be overridden per call (e.g. a management-scoped key for key-management
    endpoints). Anything else OpenRouter-specific — `json=`, `params=`,
    etc. — goes through `**kwargs`, forwarded straight to `APICaller.call`.
    """
    response_body: Any = {}
    error_message: Optional[str] = None
    response_status_code: Optional[int] = None
    response_headers: Optional[dict[str, Any]] = None
    started_at = time.perf_counter()
    request_headers = headers or {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    request_payload = to_json_safe(kwargs["json"]) if kwargs.get("json") is not None else None
    endpoint = f"{base_url.rstrip('/')}{path}"

    try:
        async with APICaller(base_url=base_url, headers=request_headers) as caller:
            openrouter_response = await caller.call(method, path, raise_for_status=raise_for_status, **kwargs)
        response_body = openrouter_response.json() if openrouter_response.content else {}
        response_status_code = openrouter_response.status_code
        response_headers = dict(openrouter_response.headers)
        endpoint = str(openrouter_response.request.url)
        return response_body
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        try:
            nickname = await query(
                db=db,
                table=Employees,
                columns=(Employees.nickname,),
                filters=(Employees.user_id == user_id,),
                fetch_one=True,
            )
            db.add(
                DfEngineOpenrouterLogs(
                    name=nickname,
                    method=method,
                    endpoint=endpoint,
                    request_headers=request_headers,
                    request_payload=request_payload,
                    response_status_code=response_status_code,
                    response_headers=response_headers,
                    response_body=response_body or None,
                    error_message=error_message,
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logging.error(f"call_openrouter: failed to persist audit log for {method} {endpoint}")
