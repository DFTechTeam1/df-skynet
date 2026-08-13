from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from error import BaseError
from error.handler import CustomError

register_error = CustomError()


def register_exception_handlers(app: FastAPI):
    app.add_exception_handler(BaseError, register_error.base_handler)
    app.add_exception_handler(RequestValidationError, register_error.pydantic_handler())
