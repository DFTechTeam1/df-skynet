from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from middlewares.lang import DEFAULT_LANG, SUPPORTED_LANGUAGES, current_lang


class LanguageMiddleware(BaseHTTPMiddleware):
    """Resolves the request language from `Accept-Language` onto `request.state.lang`
    (read by error responses) and the `current_lang` contextvar (read by
    `schemas.response.Response` to localize its default success message)."""

    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get("Accept-Language", "")
        lang = raw.split(",")[0].split(";")[0].strip().lower().split("-")[0]
        lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANG
        request.state.lang = lang
        current_lang.set(lang)
        return await call_next(request)
