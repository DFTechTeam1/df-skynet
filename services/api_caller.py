from typing import Any, Literal, Optional
from httpx import AsyncBaseTransport, AsyncClient, Response


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

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "APICaller":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()