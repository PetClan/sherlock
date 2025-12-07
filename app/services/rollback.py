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
    # Get store
    result = await db.execute(
        select(Store).where(Store.shopify_domain.contains(shop))
    )
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    if not store.access_token:
        raise HTTPException(status_code=401, detail="Store not authenticated")
    
    rollback_service = RollbackService(db)
    result = await rollback_service.rollback_file(
        store=store,
        version_id=request.version_id,
        mode=request.mode,
        user_confirmed=request.user_confirmed,
        performed_by="user",
        notes=request.notes
    )
    
    await db.commit()
    
    if not result["success"]:
        if result.get("error") == "app_owned_warning":
            # Return 409 Conflict to indicate user confirmation needed
            return {
                "success": False,
                "requires_confirmation": True,
                "warning": "app_owned",
                "message": result["message"],
                "app_owner_guess": result.get("app_owner_guess")
            }
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Rollback failed"))
    
    return result


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