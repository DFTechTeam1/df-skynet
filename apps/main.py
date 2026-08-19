from typing import Type
from fastapi import FastAPI
from fastapi_controller import register_controllers_to_app
from fastapi_utils.inferring_router import InferringRouter
from starlette.middleware.cors import CORSMiddleware
from apps.controller.common import CommonController  # noqa
from apps.controller.feature_management import FeatureManagementController  # noqa
from apps.controller.prompt_template import PromptTemplateController  # noqa
from apps.controller.user_preference import UserPreferenceController  # noqa
from apps.controller.menu_management import MenuManagementController  # noqa
from apps.controller.api_key_management import APIKeyManagementController  # noqa
from apps.controller.core import CoreDependencies, PlainDependencies
from config.openapi import scalar_config
from error.register import register_exception_handlers
from middlewares.language import LanguageMiddleware

app = FastAPI(title="DF-Skynet", version="1.0", docs_url=None, redoc_url=None)


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
