from typing import Any

from fastapi import Depends

from apps.controller import Controller
from apps.dependency.rate_limitter import rate_limit


class CoreController(Controller):
    throttle: Any = Depends(rate_limit())
