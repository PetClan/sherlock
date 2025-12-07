"""
Sherlock - Theme Snapshot Service
Fetches theme files from Shopify, calculates checksums, and tracks changes
"""

import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import httpx

from app.db.models import Store, ThemeFileVersion, DailyScan


class ThemeSnapshotService:
    """Service for capturing and comparing theme file snapshots"""
    
    API_VERSION = "2024-01"
    
    # Patterns that suggest a file is owned by an app
    APP_OWNED_PATTERNS = [
        "app", "widget", "review", "klaviyo", "privy", "loox", "judgeme",
        "recharge", "bold", "yotpo", "omnisend", "sms", "popup", "upsell",
        "crosssell", "bundle", "loyalty", "wishlist", "notify", "back-in-stock"
    ]
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_store_themes(self, store: Store) -> List[Dict[str, Any]]:
        """
        Get all themes for a store
        
        Args:
            store: The Store object with access token
            
        Returns:
            List of theme objects from Shopify
        """
        if not store.access_token:
            print(f"❌ [ThemeSnapshot] No access token for {store.shopify_domain}")
            return []
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/{self.API_VERSION}/themes.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    themes = response.json().get("themes", [])
                    print(f"✅ [ThemeSnapshot] Found {len(themes)} themes for {store.shopify_domain}")
                    return themes
                else:
                    print(f"❌ [ThemeSnapshot] Failed to fetch themes: {response.status_code}")
                    return []
                    
        except Exception as e:
            print(f"❌ [ThemeSnapshot] Error fetching themes: {e}")
            return []
    
    async def get_theme_assets(self, store: Store, theme_id: str) -> List[Dict[str, Any]]:
        """
        Get all assets (files) for a specific theme
        
        Args:
            store: The Store object
            theme_id: The Shopify theme ID
            
        Returns:
            List of asset objects
        """
        if not store.access_token:
            return []
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/{self.API_VERSION}/themes/{theme_id}/assets.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    assets = response.json().get("assets", [])
                    print(f"✅ [ThemeSnapshot] Found {len(assets)} assets in theme {theme_id}")
                    return assets
                else:
                    print(f"❌ [ThemeSnapshot] Failed to fetch assets: {response.status_code}")
                    return []
                    
        except Exception as e:
            print(f"❌ [ThemeSnapshot] Error fetching assets: {e}")
            return []
    
    async def get_asset_content(self, store: Store, theme_id: str, asset_key: str) -> Optional[str]:
        """
        Get the content of a specific asset file
        
        Args:
            store: The Store object
            theme_id: The Shopify theme ID
            asset_key: The asset key (e.g., "snippets/app-widget.liquid")
            
        Returns:
            The file content as string, or None if failed
        """
        if not store.access_token:
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/{self.API_VERSION}/themes/{theme_id}/assets.json",
                    params={"asset[key]": asset_key},
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    asset = response.json().get("asset", {})
                    return asset.get("value")
                else:
                    return None
                    
        except Exception as e:
            print(f"❌ [ThemeSnapshot] Error fetching asset {asset_key}: {e}")
            return None
    
    def calculate_hash(self, content: str) -> str:
        """Calculate SHA256 hash of content"""
        if content is None:
            return ""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def detect_app_ownership(self, file_path: str) -> tuple[bool, Optional[str]]:
        """
        Detect if a file likely belongs to an app
        
        Args:
            file_path: The file path (e.g., "snippets/klaviyo-form.liquid")
            
        Returns:
            Tuple of (is_app_owned, app_name_guess)
        """
        file_path_lower = file_path.lower()
        
        for pattern in self.APP_OWNED_PATTERNS:
            if pattern in file_path_lower:
                return True, pattern
        
        return False, None
    
    async def get_previous_version(
        self, 
        store_id: str, 
        theme_id: str, 
        file_path: str
    ) -> Optional[ThemeFileVersion]:
        """Get the most recent previous version of a file"""
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
    
    async def create_snapshot(
        self,
        store: Store,
        theme_id: str,
        theme_name: str,
        scan: DailyScan
    ) -> Dict[str, Any]:
        """
        Create a full snapshot of all theme files
        
        Args:
            store: The Store object
            theme_id: The Shopify theme ID
            theme_name: The theme name
            scan: The DailyScan record to link versions to
            
        Returns:
            Summary of snapshot results
        """
        print(f"📸 [ThemeSnapshot] Starting snapshot for theme {theme_name} ({theme_id})")
        
        # Get all assets
        assets = await self.get_theme_assets(store, theme_id)
        
        if not assets:
            return {
                "success": False,
                "error": "No assets found",
                "files_total": 0
            }
        
        results = {
            "files_total": 0,
            "files_new": 0,
            "files_changed": 0,
            "files_unchanged": 0,
            "app_owned_files": 0,
            "errors": 0
        }
        
        for asset in assets:
            asset_key = asset.get("key", "")
            
            # Skip binary files (images, fonts, etc.)
            if self._is_binary_file(asset_key):
                continue
            
            results["files_total"] += 1
            
            # Get file content
            content = await self.get_asset_content(store, theme_id, asset_key)
            
            if content is None:
                results["errors"] += 1
                continue
            
            # Calculate hash
            content_hash = self.calculate_hash(content)
            
            # Check for app ownership
            is_app_owned, app_guess = self.detect_app_ownership(asset_key)
            if is_app_owned:
                results["app_owned_files"] += 1
            
            # Get previous version
            previous = await self.get_previous_version(store.id, theme_id, asset_key)
            
            is_new = previous is None
            is_changed = not is_new and previous.content_hash != content_hash
            
            if is_new:
                results["files_new"] += 1
            elif is_changed:
                results["files_changed"] += 1
            else:
                results["files_unchanged"] += 1
            
            # Create new version record
            version = ThemeFileVersion(
                store_id=store.id,
                theme_id=theme_id,
                theme_name=theme_name,
                file_path=asset_key,
                content_hash=content_hash,
                content=content,
                file_size=len(content.encode('utf-8')),
                is_app_owned=is_app_owned,
                app_owner_guess=app_guess,
                is_new=is_new,
                is_changed=is_changed,
                previous_version_id=previous.id if previous else None,
                scan_id=scan.id
            )
            
            self.db.add(version)
        
        await self.db.flush()
        
        print(f"✅ [ThemeSnapshot] Snapshot complete: {results}")
        return results
    
    def _is_binary_file(self, file_path: str) -> bool:
        """Check if a file is binary (should be skipped)"""
        binary_extensions = [
            '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.svg',
            '.woff', '.woff2', '.ttf', '.eot', '.otf',
            '.mp4', '.webm', '.mp3', '.ogg',
            '.zip', '.gz'
        ]
        return any(file_path.lower().endswith(ext) for ext in binary_extensions)
    
    async def get_active_theme(self, store: Store) -> Optional[Dict[str, Any]]:
        """Get the currently active/published theme"""
        themes = await self.get_store_themes(store)
        
        for theme in themes:
            if theme.get("role") == "main":
                return theme
        
        return None