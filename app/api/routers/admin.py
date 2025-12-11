"""
Sherlock - Admin Portal Router
Protected admin endpoint for monitoring and oversight
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from datetime import datetime, timedelta
from typing import Optional
import os

from app.db.database import get_db
from app.db.models import Store, ReportedApp, Diagnosis, DailyScan, InstalledApp

router = APIRouter(prefix="/admin", tags=["Admin"])

# Get secrets from environment
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "sherlock-hq-2025")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "YourSecurePassword123")


def verify_secret_key(secret_key: str):
    """Verify the secret key in URL"""
    if secret_key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=404, detail="Not found")
    return True


@router.post("/{secret_key}/login")
async def admin_login(
    secret_key: str,
    password: str = Query(..., description="Admin password")
):
    """Verify admin password"""
    verify_secret_key(secret_key)
    
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    return {"success": True, "message": "Login successful"}


@router.get("/{secret_key}", response_class=HTMLResponse)
async def admin_portal(secret_key: str):
    """Serve admin portal HTML"""
    verify_secret_key(secret_key)
    
    templates_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "templates", "admin.html")
    
    if os.path.exists(templates_path):
        with open(templates_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    
    return HTMLResponse(content="<h1>Admin template not found</h1>", status_code=500)


@router.get("/{secret_key}/stats/overview")
async def get_overview_stats(
    secret_key: str,
    password: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get overview statistics"""
    verify_secret_key(secret_key)
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    try:
        # Total stores
        total_stores = await db.scalar(select(func.count(Store.id)))
        
        # Active stores (updated in last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        active_stores = await db.scalar(
            select(func.count(Store.id)).where(Store.updated_at >= week_ago)
        )
        
        # Total reports
        total_reports = await db.scalar(select(func.count(ReportedApp.id)))
        
        # Reports this week
        reports_this_week = await db.scalar(
            select(func.count(ReportedApp.id)).where(ReportedApp.first_reported >= week_ago)
        )
        
        # Try to get satisfaction stats if table exists
        avg_satisfaction = None
        total_ratings = 0
        try:
            from app.db.models import CustomerRating
            avg_satisfaction = await db.scalar(select(func.avg(CustomerRating.rating)))
            total_ratings = await db.scalar(select(func.count(CustomerRating.id))) or 0
        except:
            pass
        
        return {
            "total_stores": total_stores or 0,
            "active_stores": active_stores or 0,
            "inactive_stores": (total_stores or 0) - (active_stores or 0),
            "total_reports": total_reports or 0,
            "reports_this_week": reports_this_week or 0,
            "avg_satisfaction": avg_satisfaction,
            "total_ratings": total_ratings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{secret_key}/stores")
async def get_all_stores(
    secret_key: str,
    password: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Get all registered stores"""
    verify_secret_key(secret_key)
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    try:
        result = await db.execute(
            select(Store)
            .order_by(desc(Store.installed_at))
            .limit(limit)
            .offset(offset)
        )
        stores = result.scalars().all()
        
        total = await db.scalar(select(func.count(Store.id)))
        
        return {
            "total": total,
            "stores": [
                {
                    "id": str(s.id),
                    "shopify_domain": s.shopify_domain,
                    "shop_name": s.shop_name,
                    "email": s.email,
                    "is_active": s.is_active,
                    "created_at": s.installed_at.isoformat() if s.installed_at else None,
                    "last_scanned": s.updated_at.isoformat() if s.updated_at else None,
                    "current_risk_level": "unknown"
                }
                for s in stores
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{secret_key}/reports")
async def get_all_reports(
    secret_key: str,
    password: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Get all reported apps"""
    verify_secret_key(secret_key)
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    try:
        result = await db.execute(
            select(ReportedApp)
            .order_by(desc(ReportedApp.last_reported))
            .limit(limit)
            .offset(offset)
        )
        reports = result.scalars().all()
        
        total = await db.scalar(select(func.count(ReportedApp.id)))
        
        return {
            "total": total,
            "reports": [
                {
                    "id": str(r.id),
                    "app_name": r.app_name,
                    "report_count": r.total_reports,
                    "issue_types": r.report_reasons,
                    "risk_score": r.reddit_risk_score,
                    "reddit_mentions": r.reddit_posts_found,
                    "reddit_sentiment": r.reddit_sentiment,
                    "common_issues": r.reddit_common_issues,
                    "first_reported": r.first_reported.isoformat() if r.first_reported else None,
                    "last_reported": r.last_reported.isoformat() if r.last_reported else None
                }
                for r in reports
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{secret_key}/activity")
async def get_recent_activity(
    secret_key: str,
    password: str = Query(...),
    limit: int = Query(default=20),
    db: AsyncSession = Depends(get_db)
):
    """Get recent activity feed"""
    verify_secret_key(secret_key)
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    try:
        activities = []
        
        # Recent store registrations
        stores_result = await db.execute(
            select(Store)
            .order_by(desc(Store.installed_at))
            .limit(10)
        )
        for store in stores_result.scalars().all():
            if store.installed_at:
                activities.append({
                    "type": "store_registered",
                    "icon": "🏪",
                    "message": f"New store: {store.shopify_domain}",
                    "timestamp": store.installed_at.isoformat()
                })
        
        # Recent scans
        scans_result = await db.execute(
            select(Diagnosis, Store)
            .join(Store, Diagnosis.store_id == Store.id)
            .order_by(desc(Diagnosis.started_at))
            .limit(10)
        )
        for diag, store in scans_result.all():
            if diag.started_at:
                activities.append({
                    "type": "scan_completed",
                    "icon": "🔍",
                    "message": f"Scan completed for {store.shopify_domain}",
                    "timestamp": diag.started_at.isoformat()
                })
        
        # Recent reports
        reports_result = await db.execute(
            select(ReportedApp)
            .order_by(desc(ReportedApp.last_reported))
            .limit(10)
        )
        for report in reports_result.scalars().all():
            if report.last_reported:
                activities.append({
                    "type": "app_reported",
                    "icon": "🚨",
                    "message": f"App reported: {report.app_name}",
                    "timestamp": report.last_reported.isoformat()
                })
        
        # Sort by timestamp
        activities.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {"activities": activities[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{secret_key}/top-conflicts")
async def get_top_conflicts(
    secret_key: str,
    password: str = Query(...),
    limit: int = Query(default=10),
    db: AsyncSession = Depends(get_db)
):
    """Get top conflicting apps (reported + known conflicts combined)"""
    verify_secret_key(secret_key)
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    try:
        conflicts = []
        
        # Get reported apps with conflict-related issues
        result = await db.execute(
            select(ReportedApp)
            .where(ReportedApp.causes_conflicts == True)
            .order_by(desc(ReportedApp.total_reports))
            .limit(limit)
        )
        reported = result.scalars().all()
        
        for app in reported:
            conflicts.append({
                "app1": app.app_name,
                "app2": "Theme/Other Apps",
                "report_count": app.total_reports,
                "source": "reported"
            })
        
        # Also get apps with theme issues
        result2 = await db.execute(
            select(ReportedApp)
            .where(ReportedApp.causes_theme_issues == True)
            .order_by(desc(ReportedApp.total_reports))
            .limit(limit)
        )
        theme_issues = result2.scalars().all()
        
        for app in theme_issues:
            # Avoid duplicates
            if not any(c["app1"] == app.app_name for c in conflicts):
                conflicts.append({
                    "app1": app.app_name,
                    "app2": "Theme",
                    "report_count": app.total_reports,
                    "source": "theme_conflict"
                })
        
        # Sort by report count
        conflicts.sort(key=lambda x: x["report_count"], reverse=True)
        
        return {"conflicts": conflicts[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{secret_key}/weekly-report")
async def get_weekly_report(
    secret_key: str,
    password: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get weekly report data"""
    verify_secret_key(secret_key)
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    try:
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        
        # Calculate week range for display
        week_start = (now - timedelta(days=now.weekday())).strftime("%b %d")
        week_end = now.strftime("%b %d, %Y")
        
        # Total stores
        total_stores = await db.scalar(select(func.count(Store.id))) or 0
        
        # New installs this week
        new_installs = await db.scalar(
            select(func.count(Store.id)).where(Store.installed_at >= week_ago)
        ) or 0
        
        # Stores with daily scans configured
        daily_scan_stores = await db.scalar(
            select(func.count(func.distinct(DailyScan.store_id)))
        ) or 0
        
        daily_scan_percentage = round((daily_scan_stores / total_stores * 100) if total_stores > 0 else 0, 1)
        
        # Apps reported this week
        apps_reported = await db.scalar(
            select(func.count(ReportedApp.id)).where(ReportedApp.first_reported >= week_ago)
        ) or 0
        
        # Top reported app
        top_app_result = await db.execute(
            select(ReportedApp)
            .order_by(desc(ReportedApp.total_reports))
            .limit(1)
        )
        top_app = top_app_result.scalar()
        top_reported_app = top_app.app_name if top_app else None
        
        # Satisfaction stats
        avg_satisfaction = None
        recent_feedback = []
        try:
            from app.db.models import CustomerRating
            avg_satisfaction = await db.scalar(select(func.avg(CustomerRating.rating)))
            
            feedback_result = await db.execute(
                select(CustomerRating)
                .order_by(desc(CustomerRating.created_at))
                .limit(5)
            )
            for fb in feedback_result.scalars().all():
                recent_feedback.append({
                    "rating": fb.rating,
                    "comment": fb.comment,
                    "created_at": fb.created_at.isoformat() if fb.created_at else None
                })
        except:
            pass
        
        return {
            "week_range": f"{week_start} - {week_end}",
            "total_stores": total_stores,
            "new_installs": new_installs,
            "daily_scan_stores": daily_scan_stores,
            "daily_scan_percentage": daily_scan_percentage,
            "apps_reported": apps_reported,
            "top_reported_app": top_reported_app,
            "avg_satisfaction": avg_satisfaction,
            "recent_feedback": recent_feedback
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))