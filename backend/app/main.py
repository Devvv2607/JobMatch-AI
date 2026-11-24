import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, search, tasks
from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import install_error_handlers
from app.core.llm.availability import check_configured_models
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.redis import redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # In the background: startup must not wait on (or fail because of) a provider.
    model_check = asyncio.create_task(check_configured_models(get_settings()))
    yield
    model_check.cancel()
    # Graceful shutdown: uvicorn has stopped accepting requests and drained in-flight ones.
    await search.close_search_resources()
    await engine.dispose()
    await redis.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="JobMatch AI",
        version="0.1.0",
        description="The few jobs that fit, each with the reason and the gaps.",
        lifespan=lifespan,
    )

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(auth.router)
    v1.include_router(tasks.router)
    v1.include_router(search.router)
    app.include_router(v1)
    app.include_router(health.router)

    install_error_handlers(app)

    # Added last so it is outermost: CORS headers and request ids are present on
    # error responses too.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, hsts=settings.cookie_secure)
    return app


app = create_app()
