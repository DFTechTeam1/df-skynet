from typing import Any, Callable, Optional
from fastapi import Depends
from apps.dependency.auth import get_user
from error import AuthenticationError


def require_roles(
    roles: Optional[list[str]] = None,
    decoder: Callable = get_user,
):
    async def role_dependency(current_user: dict[str, Any] = Depends(decoder)):
        user_id = current_user.get("user_id")
        if not user_id:
            raise AuthenticationError()

        if roles:
            user_roles = current_user.get("roles")
            if not user_roles:
                raise AuthenticationError(message="no_roles_found")

            if not any(role in user_roles for role in roles):
                raise AuthenticationError(message="role_not_authorized")

        return current_user

    return role_dependency
