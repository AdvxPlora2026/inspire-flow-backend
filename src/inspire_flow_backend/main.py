from fastapi import FastAPI

from inspire_flow_backend.api.router import api_router
from inspire_flow_backend.core.config import get_settings
from inspire_flow_backend.core.errors import register_error_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.name, debug=settings.debug)
    register_error_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
