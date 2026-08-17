class AuthMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "invalid_credential": "The credential provided does not match our database.",
            "auth_not_configured": "Authentication service is not configured. Please contact your administrator.",
            "auth_unauthenticated": "You are not authenticated. Please log in and try again.",
            "permission_denied": "You do not have permission to access this feature.",
            "no_permissions_found": "Your account doesn't have any permissions assigned yet. Please contact your administrator for access.",
            "no_roles_found": "Your account doesn't have any roles assigned yet. Please contact your administrator to set up your access.",
            "role_not_authorized": "Your current role doesn't have access to this feature. Please contact your administrator if you believe this is a mistake.",
        }
