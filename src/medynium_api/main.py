from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from medynium_api import __version__
from medynium_api.api.router import api_router
from medynium_api.core.config import get_settings
from medynium_api.core.errors import ErrorBody, register_error_handlers
from medynium_api.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.app_env != "local")

    app = FastAPI(
        title="Medynium API",
        version=__version__,
        description=(
            "Governed Patient 360 and clinical agent on Snowflake. Decision support on "
            "synthetic data only. Errors use {error, message}."
        ),
        responses={
            401: {"model": ErrorBody},
            404: {"model": ErrorBody},
            501: {"model": ErrorBody},
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
