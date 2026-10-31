from fastapi import Request, Response
from apps.dependency.auth import bearer_scheme, get_user
from error import AuthenticationError, RateLimitedError
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


async def _get_user(request: Request) -> dict | None:
    """Authenticated user claims, or None. Route-level limiters run before the controller's own `get_user`,
    so `request.state.user` may not be set yet; resolve it here instead of relying on dependency order."""
    user = getattr(request.state, "user", None)
    if user is None:
        try:
            user = await get_user(request, await bearer_scheme(request))
        except AuthenticationError:
            return None  # unauthenticated: the caller falls back to the IP
    return user


class RateLimiter:
    def __init__(self, limiter: Limiter):
        self.limiter = limiter

    async def __call__(self, request: Request, _: Response):
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0] or (
            request.client.host if request.client else "127.0.0.1"
        )
        user = await _get_user(request)
        key = f"user_id:{user['user_id']}:ip:{ip}" if user else f"ip:{ip}"
        if not await self.limiter.try_acquire_async(key, blocking=False):
            raise RateLimitedError()


def rate_limit(times: int = 15, seconds: int = 1):
    return RateLimiter(limiter=Limiter(KeyedBucketFactory([Rate(times, Duration.SECOND * seconds)])))


generation_limiter = rate_limit(10, 60)  # 10 Generation per 1 Minute!


async def generation_throttle(request: Request, response: Response):
    try:
        await generation_limiter(request, response)
    except RateLimitedError as e:
        raise RateLimitedError(message="generation_rate_limit_exceeded") from e
