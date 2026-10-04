from fastapi import APIRouter

from medynium_api.features.admin.router import router as admin
from medynium_api.features.audit.router import router as audit
from medynium_api.features.auth.router import router as auth
from medynium_api.features.brief.router import router as brief
from medynium_api.features.copilot.router import router as copilot
from medynium_api.features.dashboard.router import router as dashboard
from medynium_api.features.drug_coverage.router import router as drug_coverage
from medynium_api.features.evidence.router import router as evidence
from medynium_api.features.findings.router import router as findings
from medynium_api.features.health.router import router as health
from medynium_api.features.knowledge.router import router as knowledge
from medynium_api.features.patients.router import router as patients
from medynium_api.features.pending.router import router as pending
from medynium_api.features.pins.router import router as pins
from medynium_api.features.quality.router import router as quality
from medynium_api.features.records.router import router as records
from medynium_api.features.reports.router import router as reports
from medynium_api.features.similar.router import router as similar
from medynium_api.features.views.router import router as views

api_router = APIRouter()
for feature_router in (
    health,
    auth,
    dashboard,
    patients,
    brief,
    pending,
    pins,
    records,
    reports,
    similar,
    findings,
    copilot,
    evidence,
    knowledge,
    drug_coverage,
    quality,
    views,
    audit,
    admin,
):
    api_router.include_router(feature_router)
