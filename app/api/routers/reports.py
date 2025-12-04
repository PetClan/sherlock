"""
Sherlock - Reported Apps API Router
Endpoints for reporting and viewing community-reported apps
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.reported_apps_service import ReportedAppsService

router = APIRouter(prefix="/reports", tags=["Reported Apps"])


@router.post("/app")
async def report_app(
    app_name: str = Query(..., description="Name of the problematic app"),
    shop: str = Query(..., description="Shop domain reporting the issue"),
    issue_type: str = Query(..., description="Type of issue: slowdown, conflict, checkout, theme, support"),
    description: str = Query(default="", description="Optional description of the issue"),
    db: AsyncSession = Depends(get_db)
):
    """
    Report an app as problematic
    
    This will:
    1. Search Reddit for issues with this app
    2. Store the report in the database
    3. Return findings from Reddit
    """
    try:
        service = ReportedAppsService(db)
        result = await service.report_app(
            app_name=app_name,
            shop=shop,
            issue_type=issue_type,
            description=description
        )
        await db.commit()
        return result
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to report app: {str(e)}")


@router.get("/app/{app_name}")
async def get_reported_app(
    app_name: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get report data for a specific app
    """
    try:
        service = ReportedAppsService(db)
        result = await service.get_reported_app(app_name)
        
        if not result:
            # If not in database, fetch fresh from Reddit
            from app.services.reddit_service import reddit_service
            reddit_data = await reddit_service.check_app_reputation(app_name)
            return {
                "app_name": app_name,
                "is_reported": False,
                "total_reports": 0,
                "reddit_data": reddit_data
            }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/most-reported")
async def get_most_reported_apps(
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get apps with the most community reports
    """
    try:
        service = ReportedAppsService(db)
        result = await service.get_most_reported_apps(limit=limit)
        return {"apps": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/highest-risk")
async def get_highest_risk_apps(
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get apps with highest Reddit risk scores
    """
    try:
        service = ReportedAppsService(db)
        result = await service.get_highest_risk_apps(limit=limit)
        return {"apps": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recent")
async def get_recently_reported_apps(
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get apps reported in the last N days
    """
    try:
        service = ReportedAppsService(db)
        result = await service.get_recently_reported_apps(days=days, limit=limit)
        return {"apps": result, "count": len(result), "days": days}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/discover")
async def discover_trending_issues(
    db: AsyncSession = Depends(get_db)
):
    """
    Scan Reddit for trending Shopify app issues
    Automatically discovers and stores problematic apps
    """
    try:
        service = ReportedAppsService(db)
        result = await service.discover_trending_issues()
        await db.commit()
        return result
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh")
async def refresh_reddit_data(
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh Reddit data for all reported apps
    Should be run periodically
    """
    try:
        service = ReportedAppsService(db)
        result = await service.refresh_all_reddit_data()
        await db.commit()
        return result
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))