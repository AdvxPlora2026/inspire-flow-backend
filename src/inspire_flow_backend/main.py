from fastapi import FastAPI

from inspire_flow_backend.api.router import api_router
from inspire_flow_backend.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.name, debug=settings.debug)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
