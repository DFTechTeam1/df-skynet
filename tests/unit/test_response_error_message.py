import httpx
from services.tasks.base import response_error_message

REQUEST = httpx.Request("POST", "https://tunnel.example.test/engine/storage/upload")
CLOUDFLARE_PAGE = "<!DOCTYPE html>\n<html><title>524: A timeout occurred</title>" + "x" * 6000 + "</html>"


def _response(status_code, **kwargs):
    return httpx.Response(status_code, request=REQUEST, **kwargs)


def test_html_error_page_is_summarised_not_stored_in_full():
    """A proxy's HTML error page (Cloudflare 524) becomes a one-line summary naming the status and host."""
    message = response_error_message(_response(524, text=CLOUDFLARE_PAGE))
    assert message == "HTTP 524 (non-JSON error page from tunnel.example.test)"


def test_plain_text_body_is_kept():
    """A short non-JSON, non-HTML body is returned as-is."""
    assert response_error_message(_response(502, text="Bad Gateway")) == "Bad Gateway"


def test_empty_non_json_body_falls_back_to_status():
    """An empty body yields `HTTP <status>`."""
    assert response_error_message(_response(504, content=b"")) == "HTTP 504"


def test_json_error_object_uses_its_message():
    """`{"error": {"message": ...}}` returns the nested message."""
    assert response_error_message(_response(400, json={"error": {"message": "bad file"}})) == "bad file"


def test_json_error_object_without_message_is_stringified():
    """An error dict with no message falls back to its string form."""
    assert response_error_message(_response(400, json={"error": {"code": 1}})) == "{'code': 1}"


def test_json_string_error_is_returned():
    """`{"error": "..."}` returns the string."""
    assert response_error_message(_response(400, json={"error": "nope"})) == "nope"


def test_json_top_level_message_is_used():
    """With no `error` key, the top-level `message` is returned."""
    assert response_error_message(_response(400, json={"message": "invalid"})) == "invalid"


def test_json_without_error_or_message_falls_back_to_summary():
    """A JSON body with neither key falls back to the shared plain-text summary."""
    assert response_error_message(_response(500, json={"data": []})) == '{"data":[]}'
