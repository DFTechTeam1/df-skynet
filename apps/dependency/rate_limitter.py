from fastapi import Request, Response, status
from pyrate_limiter import Duration, Limiter, Rate

from error import BaseError


class RateLimiter:
    """Per-endpoint rate limiter keyed on client IP + method + path."""

    def __init__(self, limiter: Limiter):
        self.limiter = limiter

    async def __call__(self, request: Request, _: Response):
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0] or (
            request.client.host if request.client else "127.0.0.1"
        )
        key = f"{ip}:{request.method}:{request.scope['path']}"
        if not await self.limiter.try_acquire_async(key, blocking=False):
            raise BaseError(status.HTTP_429_TOO_MANY_REQUESTS, "Too Many Requests")


def rate_limit(times: int = 15, seconds: int = 1):
    return RateLimiter(limiter=Limiter(Rate(times, Duration.SECOND * seconds)))
