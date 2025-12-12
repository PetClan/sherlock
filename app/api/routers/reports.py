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

@router.get("/investigate")
async def investigate_app(
    app_name: str = Query(..., description="Name of the app to investigate"),
    db: AsyncSession = Depends(get_db)
):
    """
    Investigate an app before installation
    Searches Reddit, Google, and our database for issues
    Returns evidence with links and snippets
    """
    try:
        results = {
            "app_name": app_name,
            "risk_score": 0,
            "reddit_results": [],
            "google_results": [],
            "database_reports": {"total": 0, "issues": []},
            "known_conflicts": []
        }
        
        risk_factors = 0
        
        # 1. Search Reddit
        try:
            from app.services.reddit_service import reddit_service
            reddit_data = await reddit_service.check_app_reputation(app_name)
            
            if reddit_data and reddit_data.get("posts"):
                for post in reddit_data["posts"][:5]:
                    results["reddit_results"].append({
                        "title": post.get("title", ""),
                        "url": post.get("url", ""),
                        "snippet": post.get("snippet", post.get("selftext", ""))[:200] if post.get("snippet") or post.get("selftext") else "",
                        "subreddit": post.get("subreddit", "shopify"),
                        "score": post.get("score", 0)
                    })
                
                # Add to risk score based on negative sentiment
                if reddit_data.get("risk_score", 0) > 5:
                    risk_factors += 3
                elif reddit_data.get("risk_score", 0) > 3:
                    risk_factors += 2
                elif reddit_data.get("negative_posts", 0) > 0:
                    risk_factors += 1
        except Exception as e:
            print(f"Reddit search error: {e}")
        
        # 2. Search Google
        try:
            from app.services.google_search_service import GoogleSearchService
            google_service = GoogleSearchService()
            google_data = await google_service.search_app_issues(app_name)
            
            if google_data and google_data.get("results"):
                for item in google_data["results"][:5]:
                    results["google_results"].append({
                        "title": item.get("title", ""),
                        "url": item.get("link", item.get("url", "")),
                        "snippet": item.get("snippet", "")[:200],
                        "source": item.get("displayLink", item.get("source", "Web"))
                    })
                
                # Add to risk based on Google findings
                if google_data.get("issues_found", 0) > 3:
                    risk_factors += 2
                elif google_data.get("issues_found", 0) > 0:
                    risk_factors += 1
        except Exception as e:
            print(f"Google search error: {e}")
        
        # 3. Check our database
        try:
            service = ReportedAppsService(db)
            db_data = await service.get_reported_app(app_name)
            
            if db_data and db_data.get("total_reports", 0) > 0:
                results["database_reports"]["total"] = db_data.get("total_reports", 0)
                
                # Group by issue type
                issue_types = {}
                if db_data.get("issues"):
                    for issue in db_data["issues"]:
                        itype = issue.get("issue_type", "other")
                        issue_types[itype] = issue_types.get(itype, 0) + 1
                
                results["database_reports"]["issues"] = [
                    {"type": k, "count": v} for k, v in issue_types.items()
                ]
                
                # Add to risk based on report count
                total = db_data.get("total_reports", 0)
                if total > 10:
                    risk_factors += 3
                elif total > 5:
                    risk_factors += 2
                elif total > 0:
                    risk_factors += 1
        except Exception as e:
            print(f"Database search error: {e}")
        
        # 4. Check known conflicts
        try:
            from app.services.conflict_database import conflict_db
            conflicts = conflict_db.get_conflicts_for_app(app_name)
            
            if conflicts:
                for conflict in conflicts[:5]:
                    other_app = conflict.get("app1") if conflict.get("app1", "").lower() != app_name.lower() else conflict.get("app2")
                    results["known_conflicts"].append({
                        "app": other_app,
                        "description": conflict.get("description", "Known compatibility issues")
                    })
                
                risk_factors += len(conflicts)
        except Exception as e:
            print(f"Conflict check error: {e}")
        
        # Calculate final risk score (0-10)
        results["risk_score"] = min(10, risk_factors)
        
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Investigation failed: {str(e)}")
    
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