"""
Google Search API Router
Endpoints for searching web for app reviews and issues arising
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from app.services.google_search_service import google_search_service

router = APIRouter(prefix="/api/v1/google", tags=["Google Search"])


@router.get("/search/{app_name}")
async def search_app(app_name: str):
    """
    Search Google for reviews and issues about a Shopify app
    """
    result = await google_search_service.search_app_reviews(app_name)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=500 if "not configured" in result.get("error", "") else 400,
            detail=result.get("error", "Search failed")
        )
    
    return result


@router.get("/conflicts/{app_name}")
async def search_conflicts(app_name: str):
    """
    Search Google specifically for app conflicts
    """
    result = await google_search_service.search_app_conflicts(app_name)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=500 if "not configured" in result.get("error", "") else 400,
            detail=result.get("error", "Search failed")
        )
    
    return result


@router.get("/alternatives/{app_name}")
async def search_alternatives(app_name: str):
    """
    Search Google for alternatives to an app
    """
    result = await google_search_service.search_app_alternatives(app_name)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=500 if "not configured" in result.get("error", "") else 400,
            detail=result.get("error", "Search failed")
        )
    
    return result


@router.get("/insights/{app_name}")
async def get_app_insights(app_name: str):
    """
    Get comprehensive insights about an app from Google search
    Combines reviews, conflicts, and sentiment analysis
    """
    result = await google_search_service.get_combined_app_insights(app_name)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=500 if "not configured" in result.get("error", "") else 400,
            detail=result.get("error", "Search failed")
        )
    
    return result