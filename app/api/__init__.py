"""
Sherlock - API Routers
"""

from fastapi import APIRouter

from app.api.routers.auth import router as auth_router


# Main API router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(auth_router)
