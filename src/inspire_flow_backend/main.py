import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import Response

from inspire_flow_backend.api.router import api_router
from inspire_flow_backend.core.config import get_settings
from inspire_flow_backend.core.errors import register_error_handlers
from inspire_flow_backend.services.agent.streaming import AgentStreamManager
from inspire_flow_backend.services.idempotency import complete_idempotency


def create_app() -> FastAPI:
    settings = get_settings()
    stream_manager = AgentStreamManager()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.agent_stream_manager = stream_manager
        yield
        await stream_manager.close()

    application = FastAPI(
        title=settings.name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    register_error_handlers(application)

    @application.middleware("http")
    async def persist_idempotency_response(request: Request, call_next):
        response = await call_next(request)
        if getattr(request.state, "idempotency_record_id", None) is None or response.headers.get(
            "content-type", ""
        ).startswith("text/event-stream"):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            decoded_body: object = json.loads(body) if body else None
        except json.JSONDecodeError:
            decoded_body = body.decode("utf-8", errors="replace")
        safe_headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower() in {"content-type", "location", "cache-control", "pragma"}
        }
        complete_idempotency(
            request,
            status_code=response.status_code,
            body=decoded_body,
            headers=safe_headers,
        )
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
