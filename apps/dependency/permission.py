from typing import Any, Optional, Callable
from fastapi import Depends
from apps.dependency.auth import get_user
from error import AuthenticationError


def require_permissions(
    permissions: Optional[list[str]] = None, decoder: Callable = get_user
):
    async def permission_dependency(current_user: dict[str, Any] = Depends(decoder)):
        user_id = current_user.get("user_id")
        if not user_id:
            raise AuthenticationError()

        if permissions:
            user_permissions = current_user.get("permissions")
            if not user_permissions:
                raise AuthenticationError(message="no_permissions_found")

            if not any(permission in user_permissions for permission in permissions):
                raise AuthenticationError(message="permission_denied")

        return current_user

    return permission_dependency
