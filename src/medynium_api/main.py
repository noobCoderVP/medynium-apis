from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from medynium_api import __version__
from medynium_api.core.config import get_settings
from medynium_api.core.errors import ErrorBody, register_error_handlers
from medynium_api.core.logging import configure_logging
from medynium_api.core.request_context import RequestContextMiddleware
from medynium_api.core.security.csrf import CsrfMiddleware
from medynium_api.core.snowflake.connection import get_pool
from medynium_api.features.copilot.router import get_ports
from medynium_api.router import api_router
from medynium_api.wiring import build_ports


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    yield
    get_pool().close_all()


def create_app() -> FastAPI:
    settings = get_settings()
    settings.assert_safe_for_environment()
    configure_logging(settings.log_level, json_logs=settings.app_env != "local")

    app = FastAPI(
        title="Medynium API",
        version=__version__,
        description=(
            "Governed Patient 360 and clinical agent on Snowflake. Decision support on synthetic data "
            "only. Errors use {error, message}. Sessions use HttpOnly cookies; state-changing requests "
            "need the X-Medynium-Client: web header."
        ),
        lifespan=lifespan,
        responses={401: {"model": ErrorBody}, 404: {"model": ErrorBody}},
    )
    # Outermost first: request context sees every response, CSRF runs before routing, CORS answers preflights.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(api_router)
    app.dependency_overrides[get_ports] = build_ports
    return app


app = create_app()
