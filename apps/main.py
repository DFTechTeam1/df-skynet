from typing import Type
from fastapi import FastAPI
from fastapi_controller.controller_utils import (
    ControllerBase,
    _get_leaf_controllers,
    _register_controller_to_router,
)
from fastapi_utils.inferring_router import InferringRouter
from starlette.middleware.cors import CORSMiddleware
from apps.controller.common import CommonController  # noqa
from apps.controller.feature_management import FeatureManagementController  # noqa
from apps.controller.prompt_template import PromptTemplateController  # noqa
from apps.controller.core import CoreDependencies, PlainDependencies
from config.openapi import scalar_config
from error.register import register_exception_handlers
from middlewares.language import LanguageMiddleware

app = FastAPI(
    title="DF-Skynet",
    version="1.0",
    docs_url=None,
)


def register_controllers_to_app(
    app: FastAPI, controller_base: Type[ControllerBase]
) -> None:
    # fastapi_controller's own register_controllers_to_app() batches every
    # leaf controller of `controller_base` onto one shared InferringRouter.
    # fastapi_utils.cbv() validates that every entry in that router's
    # `.routes` is a plain APIRoute — but on the fastapi version this project
    # pins, `router.include_router(...)` (used internally by cbv() to mount
    # each controller's routes) wraps them in an internal `_IncludedRouter`
    # node instead of flattening them. That's harmless for actual request
    # routing, but it means the *second* controller sharing a base trips
    # cbv()'s validation over the first controller's now-opaque node. Neither
    # fastapi_controller (2021) nor fastapi_utils (Nov 2024) has a newer
    # release that accounts for this, so each controller gets its own fresh
    # router here instead of sharing one.
    for controller in _get_leaf_controllers(controller_base):
        router = InferringRouter()
        _register_controller_to_router(router, controller)
        app.include_router(router)


app.openapi = lambda: scalar_config(app)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LanguageMiddleware)

register_exception_handlers(app)
register_controllers_to_app(app, CoreDependencies)
register_controllers_to_app(app, PlainDependencies)
