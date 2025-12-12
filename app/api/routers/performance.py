"""
Sherlock - Performance Timeline Router
Tracks store performance changes over time
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timedelta

from app.db.database import get_db
from app.db.models import Store, DailyScan

router = APIRouter(prefix="/performance", tags=["Performance"])


@router.get("/{shop}/history")
async def get_performance_history(
    shop: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """
    Get performance timeline for a store
    Shows scan results over time with events
    """
    # Get store
    result = await db.execute(select(Store).where(Store.shop_domain == shop))
    store = result.scalar_one_or_none()
    
    if not store:
        # Return empty history for new stores
        return {"shop": shop, "history": []}
    
    # Get scan history as performance data
    since = datetime.utcnow() - timedelta(days=days)
    
    scans_result = await db.execute(
        select(DailyScan)
        .where(DailyScan.store_id == store.id)
        .where(DailyScan.scan_date >= since)
        .order_by(desc(DailyScan.scan_date))
        .limit(50)
    )
    scans = scans_result.scalars().all()
    
    history = []
    for scan in scans:
        # Calculate a performance score from risk level
        risk_level = scan.risk_level or "low"
        if risk_level == "high":
            performance_score = 30
        elif risk_level == "medium":
            performance_score = 60
        else:
            performance_score = 90
        
        # Build event description from actual changes
        events = []
        if scan.files_changed and scan.files_changed > 0:
            events.append(f"{scan.files_changed} files changed")
        if scan.files_new and scan.files_new > 0:
            events.append(f"{scan.files_new} new files")
        if scan.files_deleted and scan.files_deleted > 0:
            events.append(f"{scan.files_deleted} files deleted")
        if scan.scripts_new and scan.scripts_new > 0:
            events.append(f"{scan.scripts_new} new scripts")
        if scan.css_issues_found and scan.css_issues_found > 0:
            events.append(f"{scan.css_issues_found} CSS issues")
        
        event = ", ".join(events) if events else scan.summary
        
        history.append({
            "recorded_at": scan.scan_date.isoformat() if scan.scan_date else None,
            "performance_score": performance_score,
            "risk_level": risk_level,
            "event": event
        })
    
    return {
        "shop": shop,
        "history": history,
        "days": days
    }


@router.get("/{shop}/latest")
async def get_latest_performance(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get most recent performance data for a store
    """
    # Get store
    result = await db.execute(select(Store).where(Store.shop_domain == shop))
    store = result.scalar_one_or_none()
    
    if not store:
        return {"shop": shop, "performance_score": None, "message": "No data yet"}
    
    # Get latest scan
    scan_result = await db.execute(
        select(DailyScan)
        .where(DailyScan.store_id == store.id)
        .order_by(desc(DailyScan.scan_date))
        .limit(1)
    )
    scan = scan_result.scalar_one_or_none()
    
    if not scan:
        return {"shop": shop, "performance_score": None, "message": "No scans yet"}
    
    risk_level = scan.risk_level or "low"
    if risk_level == "high":
        performance_score = 30
    elif risk_level == "medium":
        performance_score = 60
    else:
        performance_score = 90
    
    return {
        "shop": shop,
        "performance_score": performance_score,
        "risk_level": risk_level,
        "last_scan": scan.scan_date.isoformat() if scan.scan_date else None
    }