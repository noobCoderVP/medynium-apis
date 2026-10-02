from fastapi import APIRouter

from medynium_api.api.routes import (
    admin,
    audit,
    auth,
    copilot,
    dashboard,
    evidence,
    health,
    knowledge,
    patients,
    views,
)

api_router = APIRouter()
for module in (
    health,
    auth,
    dashboard,
    patients,
    copilot,
    evidence,
    knowledge,
    views,
    audit,
    admin,
):
    api_router.include_router(module.router)
