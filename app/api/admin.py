"""
Sherlock - Admin Portal Router
Protected admin endpoints for monitoring and oversight
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
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
        
        # Active stores (scanned in last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        active_stores = await db.scalar(
            select(func.count(Store.id)).where(Store.last_scanned >= week_ago)
        )
        
        # Total reports
        total_reports = await db.scalar(select(func.count(ReportedApp.id)))
        
        # Reports this week
        reports_this_week = await db.scalar(
            select(func.count(ReportedApp.id)).where(ReportedApp.first_reported >= week_ago)
        )
        
        # Total scans
        total_scans = await db.scalar(select(func.count(Diagnosis.id)))
        
        # Scans today
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        scans_today = await db.scalar(
            select(func.count(Diagnosis.id)).where(Diagnosis.started_at >= today)
        )
        
        # Daily scans count
        daily_scans = await db.scalar(select(func.count(DailyScan.id)))
        
        return {
            "total_stores": total_stores or 0,
            "active_stores": active_stores or 0,
            "inactive_stores": (total_stores or 0) - (active_stores or 0),
            "total_reports": total_reports or 0,
            "reports_this_week": reports_this_week or 0,
            "total_scans": total_scans or 0,
            "scans_today": scans_today or 0,
            "daily_scans_configured": daily_scans or 0
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
            .order_by(desc(Store.created_at))
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
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "last_scanned": s.last_scanned.isoformat() if s.last_scanned else None,
                    "current_risk_level": s.current_risk_level
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
                    "report_count": r.report_count,
                    "issue_types": r.issue_types,
                    "risk_score": r.risk_score,
                    "reddit_mentions": r.reddit_mentions,
                    "reddit_sentiment": r.reddit_sentiment,
                    "common_issues": r.common_issues,
                    "first_reported": r.first_reported.isoformat() if r.first_reported else None,
                    "last_reported": r.last_reported.isoformat() if r.last_reported else None
                }
                for r in reports
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{secret_key}/scans")
async def get_recent_scans(
    secret_key: str,
    password: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """Get recent scans"""
    verify_secret_key(secret_key)
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    try:
        result = await db.execute(
            select(Diagnosis, Store)
            .join(Store, Diagnosis.store_id == Store.id)
            .order_by(desc(Diagnosis.started_at))
            .limit(limit)
        )
        scans = result.all()
        
        return {
            "scans": [
                {
                    "id": str(d.id),
                    "shop": s.shopify_domain,
                    "scan_type": d.scan_type,
                    "status": d.status,
                    "issues_found": d.issues_found,
                    "started_at": d.started_at.isoformat() if d.started_at else None,
                    "completed_at": d.completed_at.isoformat() if d.completed_at else None
                }
                for d, s in scans
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
            .order_by(desc(Store.created_at))
            .limit(5)
        )
        for store in stores_result.scalars().all():
            if store.created_at:
                activities.append({
                    "type": "store_registered",
                    "icon": "🏪",
                    "message": f"New store: {store.shopify_domain}",
                    "timestamp": store.created_at.isoformat()
                })
        
        # Recent scans
        scans_result = await db.execute(
            select(Diagnosis, Store)
            .join(Store, Diagnosis.store_id == Store.id)
            .order_by(desc(Diagnosis.started_at))
            .limit(5)
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
            .limit(5)
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


@router.get("/{secret_key}/top-reported")
async def get_top_reported_apps(
    secret_key: str,
    password: str = Query(...),
    limit: int = Query(default=10),
    db: AsyncSession = Depends(get_db)
):
    """Get most reported apps"""
    verify_secret_key(secret_key)
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    try:
        result = await db.execute(
            select(ReportedApp)
            .order_by(desc(ReportedApp.report_count))
            .limit(limit)
        )
        apps = result.scalars().all()
        
        return {
            "apps": [
                {
                    "app_name": a.app_name,
                    "report_count": a.report_count,
                    "risk_score": a.risk_score,
                    "issue_types": a.issue_types
                }
                for a in apps
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))