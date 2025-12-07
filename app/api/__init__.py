"""
Sherlock - API Routers:  app/api/__init__.py
"""

from fastapi import APIRouter

from app.api.routers.auth import router as auth_router
from app.api.routers.reddit import router as reddit_router
from app.api.routers.reports import router as reports_router
from app.api.routers.google_router import router as google_router
from app.api.routers.monitoring import router as monitoring_router
from app.api.routers.rollback import router as rollback_router


# Main API router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(auth_router)
api_router.include_router(reddit_router)
api_router.include_router(reports_router)
api_router.include_router(google_router)
api_router.include_router(monitoring_router)
api_router.include_router(rollback_router)
