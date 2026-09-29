from dataclasses import dataclass
from services.redis import CacheKeys
from redis.asyncio import Redis
from redis import Redis as SyncRedis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


@dataclass
class ConnectionContext:
    db: AsyncSession
    redis: Redis
    key: CacheKeys


@dataclass
class SyncedConnectionContext:
    db: Session
    redis: SyncRedis
    key: CacheKeys
