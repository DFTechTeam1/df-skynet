from typing import Any
from fastapi import Depends
from apps.controller import Controller, ApiController
from apps.dependency.rate_limitter import rate_limit
from apps.dependency.auth import get_user
from services.mysql import get_db
from sqlalchemy.ext.asyncio import AsyncSession


class CoreDependencies(ApiController):
    throttle: Any = Depends(rate_limit())
    user: dict[str, Any] = Depends(get_user)
    db: AsyncSession = Depends(get_db)


class PlainDependencies(Controller):
    throttle: Any = Depends(rate_limit())
