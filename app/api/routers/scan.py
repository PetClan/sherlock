"""
Sherlock - Scan Router
Handles diagnostic scan endpoints
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.db.models import Store, Diagnosis
from app.services.diagnosis_service import DiagnosisService

router = APIRouter(prefix="/scan", tags=["Scan"])


class ScanRequest(BaseModel):
    shop: str
    scan_type: str = "full"  # "full", "quick", "apps_only", "theme_only"


@router.post("/start")
async def start_scan(
    request: ScanRequest,
    db: AsyncSession = Depends(get_db)
):
    """Start a diagnostic scan"""
    
    # Check kill switch first
    from app.services.system_settings_service import SystemSettingsService
    from app.services.usage_limit_service import UsageLimitService
    
    settings_service = SystemSettingsService(db)
    if not await settings_service.is_scanning_enabled():
        raise HTTPException(
            status_code=503, 
            detail="Scanning is temporarily disabled. Please try again later."
        )
    
    # Find store
    result = await db.execute(
        select(Store).where(Store.shopify_domain == request.shop)
    )
    store = result.scalar()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Check daily scan limit
    usage_service = UsageLimitService(db)
    limit_check = await usage_service.can_scan(store.id)
    
    if not limit_check["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=limit_check["message"]
        )
    
    try:
        service = DiagnosisService(db)
        diagnosis = await service.start_diagnosis(
            store_id=store.id,
            scan_type=request.scan_type
        )
        
        # Record the scan usage
        await usage_service.record_scan(store.id)
        
        await db.commit()
        
        return {
            "success": True,
            "diagnosis_id": str(diagnosis.id),
            "status": diagnosis.status,
            "scan_type": diagnosis.scan_type,
            "usage": {
                "scans_used": limit_check["current"] + 1,
                "scans_remaining": limit_check["remaining"] - 1
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{diagnosis_id}")
async def get_scan_status(
    diagnosis_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get scan status"""
    
    result = await db.execute(
        select(Diagnosis).where(Diagnosis.id == diagnosis_id)
    )
    diagnosis = result.scalar()
    
    if not diagnosis:
        raise HTTPException(status_code=404, detail="Scan not found")
    
    return {
        "diagnosis_id": str(diagnosis.id),
        "status": diagnosis.status,
        "scan_type": diagnosis.scan_type,
        "issues_found": diagnosis.issues_found,
        "started_at": diagnosis.started_at.isoformat() if diagnosis.started_at else None,
        "completed_at": diagnosis.completed_at.isoformat() if diagnosis.completed_at else None,
        "progress": 100 if diagnosis.status == "completed" else 50 if diagnosis.status == "running" else 0
    }


@router.get("/history/{shop}")
async def get_scan_history(
    shop: str,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """Get scan history for a shop"""
    
    # Find store
    result = await db.execute(
        select(Store).where(Store.shopify_domain == shop)
    )
    store = result.scalar()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Get scans
    scans_result = await db.execute(
        select(Diagnosis)
        .where(Diagnosis.store_id == store.id)
        .order_by(desc(Diagnosis.started_at))
        .limit(limit)
    )
    scans = scans_result.scalars().all()
    
    return {
        "total_scans": len(scans),
        "scans": [
            {
                "diagnosis_id": str(s.id),
                "scan_type": s.scan_type,
                "status": s.status,
                "issues_found": s.issues_found or 0,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None
            }
            for s in scans
        ]
    }


@router.get("/report/{diagnosis_id}")
async def get_scan_report(
    diagnosis_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get full scan report"""
    
    result = await db.execute(
        select(Diagnosis).where(Diagnosis.id == diagnosis_id)
    )
    diagnosis = result.scalar()
    
    if not diagnosis:
        raise HTTPException(status_code=404, detail="Scan not found")
    
    return {
        "diagnosis_id": str(diagnosis.id),
        "scan_type": diagnosis.scan_type,
        "status": diagnosis.status,
        "issues_found": diagnosis.issues_found or 0,
        "apps_scanned": diagnosis.total_apps_scanned or 0,
        "started_at": diagnosis.started_at.isoformat() if diagnosis.started_at else None,
        "completed_at": diagnosis.completed_at.isoformat() if diagnosis.completed_at else None,
        "results": diagnosis.results or {},
        "recommendations": diagnosis.recommendations or [],
        "issues": diagnosis.suspect_apps or []
    }


@router.get("/store-diagnosis/{shop}")
async def get_store_diagnosis(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get full diagnosis for a store
    Identifies issues, correlates with recent apps, and provides actions
    """
    from app.services.issue_correlation_service import IssueCorrelationService
    
    service = IssueCorrelationService(db)
    diagnosis = await service.get_store_diagnosis(shop)
    
    return diagnosis


@router.delete("/clear-issues/{shop}")
async def clear_theme_issues(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Clear all theme issues for a store (admin/debug endpoint)
    """
    from app.db.models import ThemeIssue
    
    # Find store
    result = await db.execute(
        select(Store).where(Store.shopify_domain == shop)
    )
    store = result.scalar()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Delete all theme issues for this store
    from sqlalchemy import delete
    delete_result = await db.execute(
        delete(ThemeIssue).where(ThemeIssue.store_id == store.id)
    )
    await db.commit()
    
    return {
        "success": True,
        "message": f"Cleared theme issues for {shop}",
        "deleted_count": delete_result.rowcount
    }


@router.get("/clear-issues/{shop}")
async def clear_theme_issues_get(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Clear all theme issues for a store (GET version for browser testing)
    """
    from app.db.models import ThemeIssue
    from sqlalchemy import delete
    
    # Find store
    result = await db.execute(
        select(Store).where(Store.shopify_domain == shop)
    )
    store = result.scalar()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Delete all theme issue for this store
    delete_result = await db.execute(
        delete(ThemeIssue).where(ThemeIssue.store_id == store.id)
    )
    await db.commit()
    
    return {
        "success": True,
        "message": f"Cleared theme issues for {shop}",
        "deleted_count": delete_result.rowcount
    }