from fastapi import Request, Response, status
from error import BaseError
from pyrate_limiter import (
    AbstractBucket,
    BucketFactory,
    Duration,
    InMemoryBucket,
    Limiter,
    MonotonicClock,
    Rate,
    RateItem,
)


class KeyedBucketFactory(BucketFactory):
    _clock = MonotonicClock()

    def __init__(self, rates: list[Rate]):
        self.rates = rates
        self.buckets: dict[str, AbstractBucket] = {}

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:
        return RateItem(name, self._clock.now(), weight=weight)

    def get(self, item: RateItem) -> AbstractBucket:
        bucket = self.buckets.get(item.name)
        if bucket is None:
            bucket = self.create(InMemoryBucket, self.rates)
            self.buckets[item.name] = bucket
        return bucket


class RateLimiter:
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
    return RateLimiter(
        limiter=Limiter(KeyedBucketFactory([Rate(times, Duration.SECOND * seconds)]))
    )
