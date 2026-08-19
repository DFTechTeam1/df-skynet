from fastapi_controller import create_controller

Controller = create_controller()
ApiController = create_controller(template_path_prefix="/api")
