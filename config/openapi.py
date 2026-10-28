from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def scalar_config(app: FastAPI):
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    openapi_schema.setdefault("components", {})["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    openapi_schema["servers"] = [
        {"url": "http://engine.localhost:9000", "description": "DEV"},
        {"url": "https://staging-py-engine.dfactory.pro", "description": "STG"},
    ]
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return openapi_schema
