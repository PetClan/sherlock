"""
Sherlock - Performance Timeline Router
Tracks store performance changes over time
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timedelta

from app.db.database import get_db
from app.db.models import Store, ScanResult

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
        select(ScanResult)
        .where(ScanResult.store_id == store.id)
        .where(ScanResult.scanned_at >= since)
        .order_by(desc(ScanResult.scanned_at))
        .limit(50)
    )
    scans = scans_result.scalars().all()
    
    history = []
    for scan in scans:
        # Calculate a performance score from scan data
        # Lower risk = higher performance score
        risk_score = scan.risk_score or 0
        performance_score = max(0, 100 - (risk_score * 10))
        
        # Build event description
        event = None
        if scan.apps_changed:
            event = f"Apps changed: {scan.apps_changed}"
        elif scan.files_changed:
            event = f"Theme files changed: {scan.files_changed}"
        elif scan.new_issues:
            event = f"New issues detected: {scan.new_issues}"
        
        history.append({
            "recorded_at": scan.scanned_at.isoformat() if scan.scanned_at else None,
            "performance_score": performance_score,
            "risk_score": risk_score,
            "event": event,
            "scan_type": scan.scan_type
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
        select(ScanResult)
        .where(ScanResult.store_id == store.id)
        .order_by(desc(ScanResult.scanned_at))
        .limit(1)
    )
    scan = scan_result.scalar_one_or_none()
    
    if not scan:
        return {"shop": shop, "performance_score": None, "message": "No scans yet"}
    
    risk_score = scan.risk_score or 0
    performance_score = max(0, 100 - (risk_score * 10))
    
    return {
        "shop": shop,
        "performance_score": performance_score,
        "risk_score": risk_score,
        "last_scan": scan.scanned_at.isoformat() if scan.scanned_at else None
    }