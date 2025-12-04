"""
Sherlock - Reddit API Router
"""

from fastapi import APIRouter, Query, HTTPException
from app.services.reddit_service import reddit_service

router = APIRouter(prefix="/reddit", tags=["Reddit"])


@router.get("/search/{app_name}")
async def search_app_issues(
    app_name: str,
    limit: int = Query(default=25, ge=1, le=50),
    time_filter: str = Query(default="year")
):
    try:
        results = await reddit_service.search_app_issues(
            app_name=app_name,
            limit=limit,
            time_filter=time_filter
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reputation/{app_name}")
async def check_app_reputation(app_name: str):
    try:
        result = await reddit_service.check_app_reputation(app_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trending")
async def get_trending_issues(limit: int = Query(default=10, ge=1, le=25)):
    try:
        results = await reddit_service.get_trending_issues(limit=limit)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))