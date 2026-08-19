from fastapi import FastAPI
from starlette.requests import Request
from error import BaseError, DataNotFoundError, ServiceError
from error.handler import CustomError
from error.register import register_exception_handlers

register_error = CustomError()


def _request(accept: str = "application/json") -> Request:
    scope = {"type": "http", "headers": [(b"accept", accept.encode())]}
    return Request(scope)


def test_register_exception_handlers_covers_generic_exception():
    """A raw Exception (bypassing a controller's own try/except) is still routed through our handler, not Starlette's bare default."""
    app = FastAPI()
    register_exception_handlers(app)
    assert Exception in app.exception_handlers
    assert BaseError in app.exception_handlers


def test_base_handler_json_response_never_leaks_raw_exception_text():
    """500 JSON response for an unwrapped exception never echoes the exception's own message."""
    exc = RuntimeError("super secret db connection string")
    resp = register_error.base_handler(_request("application/json"), exc)
    assert resp.status_code == 500
    assert b"super secret" not in resp.body


def test_base_handler_returns_html_page_when_browser_accept_header_is_sent():
    """500 for an unwrapped exception serves the styled HTML page when Accept asks for text/html."""
    exc = RuntimeError("boom")
    resp = register_error.base_handler(_request("text/html,application/xhtml+xml"), exc)
    assert resp.status_code == 500
    assert str(resp.path).endswith("server_error.html")


def test_base_handler_service_error_500_also_respects_accept_header():
    """A ServiceError (500 BaseError) gets the same content negotiation as an unwrapped exception."""
    json_resp = register_error.base_handler(_request("application/json"), ServiceError())
    assert json_resp.status_code == 500
    assert json_resp.headers["content-type"].startswith("application/json")

    html_resp = register_error.base_handler(_request("text/html"), ServiceError())
    assert html_resp.status_code == 500
    assert str(html_resp.path).endswith("server_error.html")


def test_base_handler_non_500_base_error_is_unaffected_by_accept_header():
    """A non-500 BaseError (e.g. 404) always returns JSON, regardless of Accept — negotiation is 500-only."""
    resp = register_error.base_handler(_request("text/html"), DataNotFoundError())
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
