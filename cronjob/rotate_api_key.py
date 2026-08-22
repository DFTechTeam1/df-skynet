import sys
import asyncio
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from apps.secret import BASE_URL, LOGIN_URL, ERP_EMAIL, ERP_PASSWORD
from log import logging
from services.api_caller import APICaller


async def login() -> dict[str, Any]:
    async with APICaller(base_url=LOGIN_URL) as caller:
        response = await caller.call("POST", "/auth/login", json={"email": ERP_EMAIL, "password": ERP_PASSWORD})
        return response.json()


async def rotate_key() -> dict[str, Any]:
    response = await login()
    header = {"Authorization": f"Bearer {(response.get('data') or {}).get('access_token', None)}"}
    async with APICaller(base_url=BASE_URL, headers=header) as caller:
        response = await caller.call("PATCH", "key-management/rotate")
        return response.json()


if __name__ == "__main__":
    asyncio.run(rotate_key())
