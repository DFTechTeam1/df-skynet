import pytest


@pytest.mark.asyncio
async def test_root_returns_the_restricted_page(client):
    """200 OK; root path returns non-empty HTML content."""
    resp = await client.call("GET", "/", raise_for_status=False)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert len(resp.content) > 0


@pytest.mark.asyncio
async def test_docs_returns_scalar_html(client):
    """200 OK; /docs returns HTML content type."""
    resp = await client.call("GET", "/docs", raise_for_status=False)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
