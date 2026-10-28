from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from error import BaseError
from error.handler import CustomError

register_error = CustomError()


def register_exception_handlers(app: FastAPI):
    app.add_exception_handler(BaseError, register_error.base_handler)
    app.add_exception_handler(RequestValidationError, register_error.pydantic_handler())
    app.add_exception_handler(StarletteHTTPException, register_error.http_handler)
    app.add_exception_handler(Exception, register_error.base_handler)
