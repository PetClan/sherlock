"""
Sherlock - Rollback Service
Restores theme files to previous versions via Shopify API
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import httpx

from app.db.models import Store, ThemeFileVersion, RollbackAction


class RollbackService:
    """Service for rolling back theme files to previous versions"""
    
    API_VERSION = "2024-01"
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_file_versions(
        self,
        store_id: str,
        theme_id: str,
        file_path: str,
        limit: int = 20
    ) -> List[ThemeFileVersion]:
        """
        Get version history for a specific file
        
        Args:
            store_id: The store ID
            theme_id: The theme ID
            file_path: The file path
            limit: Maximum versions to return
            
        Returns:
            List of ThemeFileVersion objects, newest first
        """
        result = await self.db.execute(
            select(ThemeFileVersion)
            .where(
                and_(
                    ThemeFileVersion.store_id == store_id,
                    ThemeFileVersion.theme_id == theme_id,
                    ThemeFileVersion.file_path == file_path
                )
            )
            .order_by(ThemeFileVersion.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def get_version_by_id(self, version_id: str) -> Optional[ThemeFileVersion]:
        """Get a specific file version by ID"""
        result = await self.db.execute(
            select(ThemeFileVersion).where(ThemeFileVersion.id == version_id)
        )
        return result.scalar_one_or_none()
    
    async def get_current_version(
        self,
        store_id: str,
        theme_id: str,
        file_path: str
    ) -> Optional[ThemeFileVersion]:
        """Get the most recent version of a file"""
        result = await self.db.execute(
            select(ThemeFileVersion)
            .where(
                and_(
                    ThemeFileVersion.store_id == store_id,
                    ThemeFileVersion.theme_id == theme_id,
                    ThemeFileVersion.file_path == file_path
                )
            )
            .order_by(ThemeFileVersion.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def rollback_file(
        self,
        store: Store,
        version_id: str,
        mode: str = "direct_live",
        user_confirmed: bool = False,
        performed_by: str = "user",
        notes: str = None,
        target_theme_id: str = None
    ) -> Dict[str, Any]:
        """
        Rollback a file to a previous version
        
        Args:
            store: The Store object
            version_id: The ThemeFileVersion ID to restore to
            mode: "direct_live" or "draft_theme"
            user_confirmed: User confirmed app-owned file warning
            performed_by: Who performed the action
            notes: Optional notes
            
        Returns:
            Result dict with success status and details
        """
        # Get the version to restore
        version = await self.get_version_by_id(version_id)
        
        if not version:
            return {
                "success": False,
                "error": "Version not found"
            }
        
        if version.store_id != store.id:
            return {
                "success": False,
                "error": "Version does not belong to this store"
            }
        
        # Check if app-owned and user hasn't confirmed
        if version.is_app_owned and not user_confirmed:
            return {
                "success": False,
                "error": "app_owned_warning",
                "message": "This file appears to belong to a third-party app. Rolling it back may affect that app.",
                "app_owner_guess": version.app_owner_guess,
                "requires_confirmation": True
            }
        
        # Get current version for logging
        current_version = await self.get_current_version(
            store.id, 
            version.theme_id, 
            version.file_path
        )
        
        # Create rollback action record
        rollback = RollbackAction(
            store_id=store.id,
            theme_id=version.theme_id,
            file_path=version.file_path,
            rolled_back_from_version_id=current_version.id if current_version else None,
            rolled_back_to_version_id=version.id,
            mode=mode,
            status="pending",
            was_app_owned=version.is_app_owned,
            app_owner_guess=version.app_owner_guess,
            user_confirmed=user_confirmed,
            performed_by=performed_by,
            notes=notes
        )
        self.db.add(rollback)
        await self.db.flush()
        
        # Perform the rollback via Shopify API
        # Use target_theme_id if provided, otherwise fall back to version's theme_id
        actual_theme_id = target_theme_id or version.theme_id
        try:
            success = await self._update_theme_file(
                store=store,
                theme_id=actual_theme_id,
                file_path=version.file_path,
                content=version.content
            )
            
            if success:
                rollback.status = "completed"
                rollback.completed_at = datetime.utcnow()
                await self.db.flush()
                
                print(f"✅ [Rollback] Restored {version.file_path} to version {version.id}")
                
                return {
                    "success": True,
                    "rollback_id": rollback.id,
                    "file_path": version.file_path,
                    "restored_to_version": version.id,
                    "restored_to_date": version.created_at.isoformat(),
                    "was_app_owned": version.is_app_owned,
                    "message": f"Successfully restored {version.file_path} to previous version"
                }
            else:
                rollback.status = "failed"
                rollback.error_message = "Shopify API returned error"
                await self.db.flush()
                
                return {
                    "success": False,
                    "error": "Failed to update file via Shopify API"
                }
                
        except Exception as e:
            rollback.status = "failed"
            rollback.error_message = str(e)
            await self.db.flush()
            
            print(f"❌ [Rollback] Failed: {e}")
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _update_theme_file(
        self,
        store: Store,
        theme_id: str,
        file_path: str,
        content: str
    ) -> bool:
        """
        Update a theme file via Shopify API
        
        Args:
            store: The Store object
            theme_id: The Shopify theme ID
            file_path: The asset key (e.g., "snippets/app.liquid")
            content: The file content to write
            
        Returns:
            True if successful, False otherwise
        """
        if not store.access_token:
            print(f"❌ [Rollback] No access token for {store.shopify_domain}")
            return False
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"https://{store.shopify_domain}/admin/api/{self.API_VERSION}/themes/{theme_id}/assets.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    json={
                        "asset": {
                            "key": file_path,
                            "value": content
                        }
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    print(f"✅ [Rollback] Updated {file_path} in theme {theme_id}")
                    return True
                else:
                    print(f"❌ [Rollback] Shopify API error: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            print(f"❌ [Rollback] Error updating file: {e}")
            return False
    
    async def get_rollback_history(
        self,
        store_id: str,
        limit: int = 50
    ) -> List[RollbackAction]:
        """Get rollback history for a store"""
        result = await self.db.execute(
            select(RollbackAction)
            .where(RollbackAction.store_id == store_id)
            .order_by(RollbackAction.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def get_files_with_versions(
        self,
        store_id: str,
        theme_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get list of files that have multiple versions (can be rolled back)
        
        Returns:
            List of dicts with file_path and version_count
        """
        # Get all unique file paths with their version counts
        result = await self.db.execute(
            select(
                ThemeFileVersion.file_path,
                ThemeFileVersion.is_app_owned,
                ThemeFileVersion.app_owner_guess
            )
            .where(
                and_(
                    ThemeFileVersion.store_id == store_id,
                    ThemeFileVersion.theme_id == theme_id
                )
            )
            .order_by(ThemeFileVersion.file_path)
        )
        
        rows = result.all()
        
        # Count versions per file
        file_counts = {}
        for row in rows:
            file_path = row[0]
            is_app_owned = row[1]
            app_owner = row[2]
            
            if file_path not in file_counts:
                file_counts[file_path] = {
                    "file_path": file_path,
                    "version_count": 0,
                    "is_app_owned": is_app_owned,
                    "app_owner_guess": app_owner
                }
            file_counts[file_path]["version_count"] += 1
        
        # Filter to files with multiple versions
        files_with_versions = [
            f for f in file_counts.values() 
            if f["version_count"] > 1
        ]
        
        return sorted(files_with_versions, key=lambda x: x["file_path"])
    
    async def compare_versions(
        self,
        version_id_1: str,
        version_id_2: str
    ) -> Dict[str, Any]:
        """
        Compare two versions of a file
        
        Returns:
            Dict with comparison details
        """
        v1 = await self.get_version_by_id(version_id_1)
        v2 = await self.get_version_by_id(version_id_2)
        
        if not v1 or not v2:
            return {"error": "Version not found"}
        
        if v1.file_path != v2.file_path:
            return {"error": "Cannot compare different files"}
        
        return {
            "file_path": v1.file_path,
            "version_1": {
                "id": v1.id,
                "created_at": v1.created_at.isoformat(),
                "content_hash": v1.content_hash,
                "file_size": v1.file_size,
                "content": v1.content
            },
            "version_2": {
                "id": v2.id,
                "created_at": v2.created_at.isoformat(),
                "content_hash": v2.content_hash,
                "file_size": v2.file_size,
                "content": v2.content
            },
            "same_content": v1.content_hash == v2.content_hash,
            "size_diff": (v2.file_size or 0) - (v1.file_size or 0)
        }