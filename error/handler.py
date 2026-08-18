from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from error import BaseError
from middlewares.lang import DEFAULT_LANG, resolve_message


class CustomError:
    def pydantic_handler(self):
        async def handler(_: Request, exc: Exception) -> JSONResponse:
            if not isinstance(exc, RequestValidationError):
                return JSONResponse(
                    status_code=500,
                    content={"message": "Unexpected error", "error": str(exc)},
                )

            error: dict[str, Any] = {}
            status_code = 422

            try:
                for err in exc.errors():
                    loc = err.get("loc", [])
                    if isinstance(loc[-1], int):
                        error_msg = err.get("msg")
                        ctx = err.get("ctx", {})
                        inner_error = ctx.get("error", err)
                        error["body"] = [inner_error]
                        return JSONResponse(
                            status_code=status_code,
                            content={
                                "message": error_msg,
                                "error": error,
                            },
                        )
                    else:
                        key = loc[-1]
                        error[key] = [err.get("msg", None)]

            except IndexError as e:
                error["unknown"] = [str(e)]

            return JSONResponse(
                status_code=status_code,
                content={
                    "message": "Malformed JSON.",
                    "error": error,
                },
            )

        return handler

    def base_handler(self, request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, BaseError):
            lang = getattr(request.state, "lang", DEFAULT_LANG)
            error = (
                {field: [resolve_message(msg, lang) for msg in messages] for field, messages in exc.error.items()}
                if exc.error
                else exc.error
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "message": resolve_message(exc.message, lang),
                    "error": error,
                },
            )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": "Internal server error.", "error": str(exc)},
        )
