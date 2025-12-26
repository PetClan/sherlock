"""
Sherlock - Rollback API Router
Endpoints for file version history and rollback functionality
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import Store, ThemeFileVersion, RollbackAction
from app.services.rollback_service import RollbackService
from app.services.theme_snapshot_service import ThemeSnapshotService


router = APIRouter(prefix="/rollback", tags=["Rollback"])


class RollbackRequest(BaseModel):
    version_id: str
    mode: str = "direct_live"  # "direct_live" or "draft_theme"
    user_confirmed: bool = False
    notes: Optional[str] = None

class FullRestoreRequest(BaseModel):
    date: str  # YYYY-MM-DD format
    theme_id: Optional[str] = None
    mode: str = "direct_live"


@router.get("/files/{shop}")
async def get_files_with_versions(
    shop: str,
    theme_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of files that have version history (can be rolled back)
    """
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Get active theme if not specified
    if not theme_id:
        theme_service = ThemeSnapshotService(db)
        active_theme = await theme_service.get_active_theme(store)
        if active_theme:
            theme_id = str(active_theme.get("id", ""))
        else:
            raise HTTPException(status_code=404, detail="No active theme found")
    
    rollback_service = RollbackService(db)
    files = await rollback_service.get_files_with_versions(store.id, theme_id)
    
    return {
        "shop": store.shopify_domain,
        "theme_id": theme_id,
        "total_files": len(files),
        "files": files
    }


@router.get("/versions/{shop}/{file_path:path}")
async def get_file_versions(
    shop: str,
    file_path: str,
    theme_id: Optional[str] = None,
    limit: int = Query(default=20, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get version history for a specific file
    """
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Get active theme if not specified
    if not theme_id:
        theme_service = ThemeSnapshotService(db)
        active_theme = await theme_service.get_active_theme(store)
        if active_theme:
            theme_id = str(active_theme.get("id", ""))
        else:
            raise HTTPException(status_code=404, detail="No active theme found")
    
    rollback_service = RollbackService(db)
    versions = await rollback_service.get_file_versions(
        store_id=store.id,
        theme_id=theme_id,
        file_path=file_path,
        limit=limit
    )
    
    return {
        "shop": store.shopify_domain,
        "theme_id": theme_id,
        "file_path": file_path,
        "total_versions": len(versions),
        "versions": [
            {
                "id": v.id,
                "content_hash": v.content_hash,
                "file_size": v.file_size,
                "is_app_owned": v.is_app_owned,
                "app_owner_guess": v.app_owner_guess,
                "is_new": v.is_new,
                "is_changed": v.is_changed,
                "created_at": v.created_at.isoformat()
            }
            for v in versions
        ]
    }


@router.get("/version/{version_id}")
async def get_version_details(
    version_id: str,
    include_content: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """
    Get details of a specific file version
    """
    rollback_service = RollbackService(db)
    version = await rollback_service.get_version_by_id(version_id)
    
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    response = {
        "id": version.id,
        "store_id": version.store_id,
        "theme_id": version.theme_id,
        "theme_name": version.theme_name,
        "file_path": version.file_path,
        "content_hash": version.content_hash,
        "file_size": version.file_size,
        "is_app_owned": version.is_app_owned,
        "app_owner_guess": version.app_owner_guess,
        "is_new": version.is_new,
        "is_changed": version.is_changed,
        "created_at": version.created_at.isoformat()
    }
    
    if include_content:
        response["content"] = version.content
    
    return response


@router.post("/restore/{shop}")
async def rollback_file(
    shop: str,
    request: RollbackRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Rollback a file to a previous version
    
    If the file is app-owned, set user_confirmed=true to proceed despite warning.
    """
    from app.services.usage_limit_service import UsageLimitService
    
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    if not store.access_token:
        raise HTTPException(status_code=401, detail="Store not authenticated")
    
    # Check daily restore limit
    usage_service = UsageLimitService(db)
    limit_check = await usage_service.can_restore(store.id)
    
    if not limit_check["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=limit_check["message"]
        )
    
    rollback_service = RollbackService(db)
    rollback_result = await rollback_service.rollback_file(
        store=store,
        version_id=request.version_id,
        mode=request.mode,
        user_confirmed=request.user_confirmed,
        performed_by="user",
        notes=request.notes
    )
    
    if not rollback_result["success"]:
        if rollback_result.get("error") == "app_owned_warning":
            # Return 409 Conflict to indicate user confirmation needed
            return {
                "success": False,
                "requires_confirmation": True,
                "warning": "app_owned",
                "message": rollback_result["message"],
                "app_owner_guess": rollback_result.get("app_owner_guess")
            }
        elif rollback_result.get("error") == "read_only_mode":
            raise HTTPException(status_code=503, detail=rollback_result["message"])
        else:
            raise HTTPException(status_code=400, detail=rollback_result.get("error", "Rollback failed"))
    
    # Record the restore usage (only after success)
    await usage_service.record_restore(store.id)
    
    await db.commit()
    
    # Add usage info to response
    rollback_result["usage"] = {
        "restores_used": limit_check["current"] + 1,
        "restores_remaining": limit_check["remaining"] - 1
    }
    
    return rollback_result


@router.get("/history/{shop}")
async def get_rollback_history(
    shop: str,
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Get rollback history for a store
    """
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    rollback_service = RollbackService(db)
    history = await rollback_service.get_rollback_history(store.id, limit)
    
    return {
        "shop": store.shopify_domain,
        "total_rollbacks": len(history),
        "rollbacks": [
            {
                "id": r.id,
                "file_path": r.file_path,
                "theme_id": r.theme_id,
                "mode": r.mode,
                "status": r.status,
                "was_app_owned": r.was_app_owned,
                "app_owner_guess": r.app_owner_guess,
                "performed_by": r.performed_by,
                "notes": r.notes,
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "error_message": r.error_message
            }
            for r in history
        ]
    }


@router.get("/compare")
async def compare_versions(
    version_id_1: str,
    version_id_2: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Compare two versions of a file
    """
    rollback_service = RollbackService(db)
    result = await rollback_service.compare_versions(version_id_1, version_id_2)
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result
@router.post("/restore-full/{shop}")
async def restore_full_theme(
    shop: str,
    request: FullRestoreRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Restore all theme files to a specific date.
    This will restore every file that has a version from that date.
    """
    from datetime import datetime, timedelta
    from app.services.system_settings_service import SystemSettingsService
    from app.services.usage_limit_service import UsageLimitService
    
    # Check read-only mode first
    settings_service = SystemSettingsService(db)
    if not await settings_service.is_restores_enabled():
        raise HTTPException(
            status_code=503,
            detail="Theme restores are currently disabled (read-only mode active). Please try again later."
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

    # Check daily restore limit
    usage_service = UsageLimitService(db)
    limit_check = await usage_service.can_restore(store.id)
    
    if not limit_check["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=limit_check["message"]
        )

    # Get active theme if not specified
    theme_id = request.theme_id
    if not theme_id:
        theme_service = ThemeSnapshotService(db)
        active_theme = await theme_service.get_active_theme(store)
        if active_theme:
            theme_id = str(active_theme.get("id", ""))
        else:
            raise HTTPException(status_code=404, detail="No active theme found")

    # Parse date and create date range
    try:
        target_date = datetime.strptime(request.date, "%Y-%m-%d")
        date_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    rollback_service = RollbackService(db)
    
    # Get all files with versions
    files = await rollback_service.get_files_with_versions(store.id, theme_id)
    
    # Phase 1: Gather all files that need restoration (parallel DB lookups)
    print(f"🔄 [Rollback] Preparing restore for {len(files)} files...")
    
    async def prepare_file(file_info):
        """Prepare a single file for restoration - find target version"""
        file_path = file_info["file_path"]
        
        versions = await rollback_service.get_file_versions(
            store_id=store.id,
            theme_id=theme_id,
            file_path=file_path,
            limit=50
        )
        
        # Find the latest version from the target date
        target_version = None
        for v in versions:
            version_date = v.created_at.replace(tzinfo=None)
            if date_start <= version_date <= date_end:
                target_version = v
                break
        
        if not target_version:
            # No version from that date, try to find the most recent version BEFORE that date
            for v in versions:
                version_date = v.created_at.replace(tzinfo=None)
                if version_date < date_start:
                    target_version = v
                    break
        
        if not target_version:
            return {"status": "skip", "file_path": file_path, "reason": "no_version"}
        
        # Check if this version is already the current version
        if versions and versions[0].id == target_version.id:
            return {"status": "skip", "file_path": file_path, "reason": "already_current"}
        
        return {
            "status": "restore",
            "file_path": file_path,
            "version_id": target_version.id,
            "version": target_version
        }
    
    # Parallel preparation of all files
    import asyncio
    preparation_results = await asyncio.gather(*[prepare_file(f) for f in files])
    
    # Separate files to restore from files to skip
    files_to_restore = [r for r in preparation_results if r["status"] == "restore"]
    files_skipped = len([r for r in preparation_results if r["status"] == "skip"])
    
    print(f"🔄 [Rollback] {len(files_to_restore)} files to restore, {files_skipped} skipped")
    
    # Phase 2: Perform restorations in parallel batches
    BATCH_SIZE = 2  # Shopify allows max 2 calls per second
    files_restored = 0
    errors = []
    
    async def restore_file(file_data):
        """Restore a single file - direct Shopify API call (no DB logging for speed)"""
        try:
            # Call the Shopify API directly to avoid DB session conflicts
            success = await rollback_service._update_theme_file(
                store=store,
                theme_id=theme_id,
                file_path=file_data["file_path"],
                content=file_data["version"].content
            )
            
            if success:
                return {"status": "success", "file_path": file_data["file_path"]}
            else:
                return {"status": "error", "file_path": file_data["file_path"], "error": "Shopify API error"}
        except Exception as e:
            return {"status": "error", "file_path": file_data["file_path"], "error": str(e)}
    
    # Process in batches
    for i in range(0, len(files_to_restore), BATCH_SIZE):
        batch = files_to_restore[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(files_to_restore) + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"🔄 [Rollback] Processing batch {batch_num}/{total_batches} ({len(batch)} files)...")
        
        # Run batch in parallel
        batch_results = await asyncio.gather(*[restore_file(f) for f in batch])
        
        # Count results
        for result in batch_results:
            if result["status"] == "success":
                files_restored += 1
            else:
                errors.append({
                    "file": result["file_path"],
                    "error": result.get("error", "Unknown error")
                })
        
        # Delay between batches to respect Shopify's 2 calls/second limit
        if i + BATCH_SIZE < len(files_to_restore):
            await asyncio.sleep(1.0)
    
    print(f"✅ [Rollback] Complete: {files_restored} restored, {files_skipped} skipped, {len(errors)} errors")

    # Record restore usage only if files were actually restored
    if files_restored > 0:
        await usage_service.record_restore(store.id)
    
    await db.commit()

    return {
        "success": True,
        "date": request.date,
        "theme_id": theme_id,
        "files_restored": files_restored,
        "files_skipped": files_skipped,
        "total_files": len(files),
        "errors": errors if errors else None,
        "usage": {
            "restores_used": limit_check["current"] + (1 if files_restored > 0 else 0),
            "restores_remaining": limit_check["remaining"] - (1 if files_restored > 0 else 0)
        }
    }
@router.get("/debug/{shop}")
async def debug_rollback(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug endpoint to diagnose rollback issues"""
    import httpx
    
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        return {"error": "Store not found"}
    
    # Get active theme
    theme_service = ThemeSnapshotService(db)
    active_theme = await theme_service.get_active_theme(store)
    
    if not active_theme:
        return {"error": "No active theme found"}
    
    theme_id = active_theme.get("id")
    
    debug_results = {
        "shop": store.shopify_domain,
        "active_theme_id": theme_id,
        "active_theme_name": active_theme.get("name"),
    }
    
    async with httpx.AsyncClient() as client:
        # Test 1: Can we GET the theme?
        theme_response = await client.get(
            f"https://{store.shopify_domain}/admin/api/2024-01/themes/{theme_id}.json",
            headers={"X-Shopify-Access-Token": store.access_token}
        )
        debug_results["get_theme_status"] = theme_response.status_code
        
        # Test 2: Can we GET an asset?
        asset_response = await client.get(
            f"https://{store.shopify_domain}/admin/api/2024-01/themes/{theme_id}/assets.json?asset[key]=layout/theme.liquid",
            headers={"X-Shopify-Access-Token": store.access_token}
        )
        debug_results["get_asset_status"] = asset_response.status_code
        
        # Test 3: Try a PUT (this will likely fail)
        if asset_response.status_code == 200:
            asset_data = asset_response.json()
            original_content = asset_data.get("asset", {}).get("value", "")
            
            # Try to PUT the same content back (no actual change)
            put_response = await client.put(
                f"https://{store.shopify_domain}/admin/api/2024-01/themes/{theme_id}/assets.json",
                headers={
                    "X-Shopify-Access-Token": store.access_token,
                    "Content-Type": "application/json"
                },
                json={
                    "asset": {
                        "key": "layout/theme.liquid",
                        "value": original_content
                    }
                }
            )
            debug_results["put_asset_status"] = put_response.status_code
            debug_results["put_asset_response"] = put_response.text[:500]
            debug_results["put_request_id"] = put_response.headers.get("x-request-id")
    
    return debug_results
