"""
Sherlock - Monitoring API Router
Endpoints for daily scans, theme monitoring, and script tracking
"""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import Store, DailyScan, ThemeFileVersion, ScriptTagSnapshot
from app.services.daily_scan_service import DailyScanService


router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@router.post("/scan/{shop}")
async def trigger_daily_scan(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger a daily monitoring scan for a store
    
    This will:
    - Snapshot all theme files
    - Track script tags
    - Detect CSS risks
    - Calculate overall risk level
    """
    # Check kill switch first
    from app.services.system_settings_service import SystemSettingsService
    from app.services.usage_limit_service import UsageLimitService
    
    settings_service = SystemSettingsService(db)
    if not await settings_service.is_scanning_enabled():
        raise HTTPException(
            status_code=503, 
            detail="Scanning is temporarily disabled. Please try again later."
        )
    
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    if not store.access_token:
        raise HTTPException(status_code=401, detail="Store not authenticated")
    
    # Check daily scan limit
    usage_service = UsageLimitService(db)
    limit_check = await usage_service.can_scan(store.id)
    
    if not limit_check["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=limit_check["message"]
        )
    
    # Run scan
    scan_service = DailyScanService(db)
    scan = await scan_service.run_daily_scan(store)
    
    # Record the scan usage
    await usage_service.record_scan(store.id)
    
    await db.commit()
    
    return {
        "success": True,
        "scan_id": scan.id,
        "status": scan.status,
        "risk_level": scan.risk_level,
        "summary": scan.summary,
        "files_total": scan.files_total,
        "files_changed": scan.files_changed,
        "files_new": scan.files_new,
        "scripts_total": scan.scripts_total,
        "scripts_new": scan.scripts_new,
        "scripts_removed": scan.scripts_removed,
        "css_issues_found": scan.css_issues_found,
        "risk_reasons": scan.risk_reasons,
        "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        "usage": {
            "scans_used": limit_check["current"] + 1,
            "scans_remaining": limit_check["remaining"] - 1
        }
    }


@router.get("/scans/{shop}")
async def get_scan_history(
    shop: str,
    limit: int = Query(default=30, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Get scan history for a store"""
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Get scans
    scan_service = DailyScanService(db)
    scans = await scan_service.get_scan_history(store.id, limit)
    
    return {
        "shop": store.shopify_domain,
        "total_scans": len(scans),
        "scans": [
            {
                "id": scan.id,
                "scan_date": scan.scan_date.isoformat(),
                "status": scan.status,
                "risk_level": scan.risk_level,
                "summary": scan.summary,
                "files_changed": scan.files_changed,
                "files_new": scan.files_new,
                "scripts_new": scan.scripts_new,
                "css_issues_found": scan.css_issues_found
            }
            for scan in scans
        ]
    }


@router.get("/scan/{scan_id}")
async def get_scan_details(
    scan_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed results for a specific scan"""
    # Get scan
    result = await db.execute(
        select(DailyScan).where(DailyScan.id == scan_id)
    )
    scan = result.scalar_one_or_none()
    
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    
    # Get changed files
    scan_service = DailyScanService(db)
    changed_files = await scan_service.get_changed_files_for_scan(scan_id)
    new_files = await scan_service.get_new_files_for_scan(scan_id)
    new_scripts = await scan_service.get_new_scripts_for_scan(scan_id)
    
    return {
        "id": scan.id,
        "scan_date": scan.scan_date.isoformat(),
        "status": scan.status,
        "risk_level": scan.risk_level,
        "risk_reasons": scan.risk_reasons,
        "summary": scan.summary,
        "files_total": scan.files_total,
        "files_changed": scan.files_changed,
        "files_new": scan.files_new,
        "files_deleted": scan.files_deleted,
        "scripts_total": scan.scripts_total,
        "scripts_new": scan.scripts_new,
        "scripts_removed": scan.scripts_removed,
        "css_issues_found": scan.css_issues_found,
        "non_namespaced_css": scan.non_namespaced_css,
        "scan_metadata": scan.scan_metadata,
        "changed_files": [
            {
                "file_path": f.file_path,
                "is_app_owned": f.is_app_owned,
                "app_owner_guess": f.app_owner_guess
            }
            for f in changed_files
        ],
        "new_files": [
            {
                "file_path": f.file_path,
                "is_app_owned": f.is_app_owned,
                "app_owner_guess": f.app_owner_guess
            }
            for f in new_files
        ],
        "new_scripts": [
            {
                "src": s.src,
                "likely_app": s.likely_app,
                "display_scope": s.display_scope
            }
            for s in new_scripts
        ],
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "completed_at": scan.completed_at.isoformat() if scan.completed_at else None
    }


@router.get("/files/{shop}")
async def get_theme_files(
    shop: str,
    theme_id: Optional[str] = None,
    app_owned_only: bool = False,
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db)
):
    """Get latest theme file versions for a store"""
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Build query
    query = select(ThemeFileVersion).where(
        ThemeFileVersion.store_id == store.id
    )
    
    if theme_id:
        query = query.where(ThemeFileVersion.theme_id == theme_id)
    
    if app_owned_only:
        query = query.where(ThemeFileVersion.is_app_owned == True)
    
    query = query.order_by(ThemeFileVersion.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    files = result.scalars().all()
    
    return {
        "shop": store.shopify_domain,
        "total_files": len(files),
        "files": [
            {
                "id": f.id,
                "file_path": f.file_path,
                "theme_id": f.theme_id,
                "theme_name": f.theme_name,
                "content_hash": f.content_hash,
                "file_size": f.file_size,
                "is_app_owned": f.is_app_owned,
                "app_owner_guess": f.app_owner_guess,
                "is_new": f.is_new,
                "is_changed": f.is_changed,
                "created_at": f.created_at.isoformat()
            }
            for f in files
        ]
    }


@router.get("/scripts/{shop}")
async def get_script_tags(
    shop: str,
    include_removed: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """Get script tags for a store"""
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Build query
    query = select(ScriptTagSnapshot).where(
        ScriptTagSnapshot.store_id == store.id
    )
    
    if not include_removed:
        query = query.where(ScriptTagSnapshot.is_removed == False)
    
    query = query.order_by(ScriptTagSnapshot.first_seen.desc())
    
    result = await db.execute(query)
    scripts = result.scalars().all()
    
    return {
        "shop": store.shopify_domain,
        "total_scripts": len(scripts),
        "scripts": [
            {
                "id": s.id,
                "src": s.src,
                "likely_app": s.likely_app,
                "display_scope": s.display_scope,
                "event": s.event,
                "is_new": s.is_new,
                "is_removed": s.is_removed,
                "first_seen": s.first_seen.isoformat(),
                "last_seen": s.last_seen.isoformat()
            }
            for s in scripts
        ]
    }


@router.get("/latest/{shop}")
async def get_latest_scan(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """Get the most recent scan for a store"""
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Get latest scan
    scan_service = DailyScanService(db)
    scan = await scan_service.get_latest_scan(store.id)
    
    if not scan:
        return {
            "shop": store.shopify_domain,
            "has_scan": False,
            "message": "No scans have been run yet"
        }
    
    return {
        "shop": store.shopify_domain,
        "has_scan": True,
        "scan": {
            "id": scan.id,
            "scan_date": scan.scan_date.isoformat(),
            "status": scan.status,
            "risk_level": scan.risk_level,
            "risk_reasons": scan.risk_reasons,
            "summary": scan.summary,
            "files_total": scan.files_total,
            "files_changed": scan.files_changed,
            "files_new": scan.files_new,
            "scripts_total": scan.scripts_total,
            "scripts_new": scan.scripts_new,
            "css_issues_found": scan.css_issues_found
        }
    }
@router.get("/scan-all")
async def scan_all_stores(
    api_key: str = Query(default=None, description="Secret API key for cron jobs"),
    db: AsyncSession = Depends(get_db)
):
    """
    Scan all active stores - designed for cron job use
    
    This endpoint scans every store that has:
    - A valid access token
    - Is not currently being scanned
    
    Returns a summary of all scan results.
    """
    import os
    
    # Verify API key for security
    expected_key = os.getenv("CRON_API_KEY")
    if expected_key and api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Get all stores with access tokens
    result = await db.execute(
        select(Store).where(Store.access_token.isnot(None))
    )
    stores = result.scalars().all()
    
    if not stores:
        return {
            "success": True,
            "message": "No stores to scan",
            "stores_scanned": 0,
            "results": []
        }
    
    scan_service = DailyScanService(db)
    results = []
    errors = []
    
    for store in stores:
        try:
            print(f"🔍 [Cron] Scanning {store.shopify_domain}...")
            scan = await scan_service.run_daily_scan(store)
            
            results.append({
                "shop": store.shopify_domain,
                "success": True,
                "scan_id": scan.id,
                "risk_level": scan.risk_level,
                "files_new": scan.files_new,
                "files_changed": scan.files_changed,
                "css_issues_found": scan.css_issues_found
            })
            
            print(f"✅ [Cron] Completed {store.shopify_domain} - {scan.risk_level} risk")
            
        except Exception as e:
            print(f"❌ [Cron] Failed {store.shopify_domain}: {str(e)}")
            errors.append({
                "shop": store.shopify_domain,
                "success": False,
                "error": str(e)
            })
    
    await db.commit()
    
    return {
        "success": True,
        "message": f"Scanned {len(results)} stores",
        "stores_scanned": len(results),
        "stores_failed": len(errors),
        "results": results,
        "errors": errors
    }