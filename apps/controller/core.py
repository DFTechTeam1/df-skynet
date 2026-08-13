from typing import Any

from fastapi import Depends

from apps.controller import Controller
from apps.dependency.rate_limitter import rate_limit


class CoreController(Controller):
    throttle: Any = Depends(rate_limit())
    # Will be added decoder token here, so only allowed user can access the API. If not, will return 401 Unauthorized.
