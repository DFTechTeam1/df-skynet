from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from middlewares.lang import DEFAULT_LANG, SUPPORTED_LANGUAGES


class LanguageMiddleware(BaseHTTPMiddleware):
    """Resolves the request language from `Accept-Language` onto `request.state.lang`."""

    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get("Accept-Language", "")
        lang = raw.split(",")[0].split(";")[0].strip().lower().split("-")[0]
        request.state.lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANG
        return await call_next(request)
