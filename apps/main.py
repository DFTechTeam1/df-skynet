from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi_controller import register_controllers_to_app
from starlette.middleware.cors import CORSMiddleware

from apps.controller.common import CommonController  # noqa
from apps.controller.core import CoreController
from config.openapi import scalar_config
from error.register import register_exception_handlers
from middlewares.language import LanguageMiddleware
from utils import get_project_root

app = FastAPI(
    title="ERP-LAX-Python",
    version="1.0",
    docs_url=None,
)

app.openapi = lambda: scalar_config(app)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LanguageMiddleware)
app.mount(
    "/static", StaticFiles(directory=get_project_root() / "static"), name="static"
)

register_exception_handlers(app)
register_controllers_to_app(app, CoreController)
