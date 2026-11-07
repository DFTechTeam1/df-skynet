import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi_controller import register_controllers_to_app
from starlette.middleware.cors import CORSMiddleware
from apps.controller.common import CommonController  # noqa
from apps.controller.feature_management import FeatureManagementController  # noqa
from apps.controller.prompt_template import PromptTemplateController  # noqa
from apps.controller.user_preference import UserPreferenceController  # noqa
from apps.controller.menu_management import MenuManagementController  # noqa
from apps.controller.api_key_management import APIKeyManagementController  # noqa
from apps.controller.api_logs import ApiLogsController  # noqa
from apps.controller.model_management import ModelManagementController  # noqa
from apps.controller.setting import SettingController  # noqa
from apps.controller.files import FilesController  # noqa
from apps.controller.generations import GenerationsController  # noqa
from apps.controller.pusher import PusherController  # noqa
from apps.controller.chat import ChatController  # noqa
from apps.controller.core import CoreDependencies, PlainDependencies
from config.openapi import scalar_config
from error.register import register_exception_handlers
from middlewares.language import LanguageMiddleware
from apps.secret import CORS_ALLOWED_ORIGINS
from services.chat_assistant import CHAT_STORAGE_DIR
from services.frame_reference_color import FRAME_COLOR_DIR

app = FastAPI(title="DF-Skynet", version="1.0", docs_url=None, redoc_url=None)


app.openapi = lambda: scalar_config(app)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LanguageMiddleware)
os.makedirs(CHAT_STORAGE_DIR, exist_ok=True)
os.makedirs(FRAME_COLOR_DIR, exist_ok=True)

app.mount("/api/storages/chat_assistants", StaticFiles(directory=CHAT_STORAGE_DIR), name="chat_assistants")
app.mount("/api/storages/frame_reference_colors", StaticFiles(directory=FRAME_COLOR_DIR), name="frame_reference_colors")
register_exception_handlers(app)
register_controllers_to_app(app, CoreDependencies)
register_controllers_to_app(app, PlainDependencies)
