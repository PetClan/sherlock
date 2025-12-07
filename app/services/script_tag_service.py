"""
Sherlock - Script Tag Tracking Service
Monitors script tags injected by apps and tracks changes over time
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import httpx

from app.db.models import Store, ScriptTagSnapshot, DailyScan


class ScriptTagService:
    """Service for tracking script tags injected by Shopify apps"""
    
    API_VERSION = "2024-01"
    
    # Patterns to identify which app likely added a script
    APP_SCRIPT_PATTERNS = {
        "klaviyo": ["klaviyo.com", "klaviyo.js"],
        "privy": ["privy.com", "widget.privy"],
        "loox": ["loox.io", "loox.app"],
        "judgeme": ["judge.me", "judgeme"],
        "yotpo": ["yotpo.com", "staticw2.yotpo"],
        "omnisend": ["omnisend.com", "omnisrc"],
        "recharge": ["recharge.com", "rechargepayments"],
        "bold": ["boldapps.net", "boldcommerce"],
        "stamped": ["stamped.io"],
        "smile": ["smile.io"],
        "gorgias": ["gorgias.chat", "gorgias.io"],
        "tidio": ["tidio.co", "tidiochat"],
        "zendesk": ["zendesk.com", "zdassets"],
        "intercom": ["intercom.io", "intercomcdn"],
        "hotjar": ["hotjar.com"],
        "lucky_orange": ["luckyorange.com"],
        "google_analytics": ["google-analytics.com", "googletagmanager.com", "gtag"],
        "facebook_pixel": ["facebook.net", "fbevents", "connect.facebook"],
        "tiktok_pixel": ["tiktok.com", "analytics.tiktok"],
        "pinterest": ["pintrk", "pinterest.com"],
        "snapchat": ["snapchat.com", "snap.licdn"],
        "afterpay": ["afterpay.com", "afterpay.js"],
        "klarna": ["klarna.com", "klarna-"],
        "shopify_shop": ["shop.app", "shopify-shop"],
        "pagefly": ["pagefly.io"],
        "shogun": ["getshogun.com"],
    }
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_script_tags(self, store: Store) -> List[Dict[str, Any]]:
        """
        Get all script tags for a store from Shopify API
        
        Args:
            store: The Store object with access token
            
        Returns:
            List of script tag objects from Shopify
        """
        if not store.access_token:
            print(f"❌ [ScriptTag] No access token for {store.shopify_domain}")
            return []
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/{self.API_VERSION}/script_tags.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    script_tags = response.json().get("script_tags", [])
                    print(f"✅ [ScriptTag] Found {len(script_tags)} script tags for {store.shopify_domain}")
                    return script_tags
                elif response.status_code == 403:
                    print(f"⚠️ [ScriptTag] No permission to read script tags (need read_script_tags scope)")
                    return []
                else:
                    print(f"❌ [ScriptTag] Failed to fetch script tags: {response.status_code}")
                    return []
                    
        except Exception as e:
            print(f"❌ [ScriptTag] Error fetching script tags: {e}")
            return []
    
    def identify_app(self, script_src: str) -> Optional[str]:
        """
        Identify which app likely added a script based on URL patterns
        
        Args:
            script_src: The script URL
            
        Returns:
            App name if identified, None otherwise
        """
        script_src_lower = script_src.lower()
        
        for app_name, patterns in self.APP_SCRIPT_PATTERNS.items():
            for pattern in patterns:
                if pattern in script_src_lower:
                    return app_name
        
        return None
    
    async def get_previous_scripts(self, store_id: str, scan_id: str = None) -> List[ScriptTagSnapshot]:
        """
        Get the most recent script tag snapshots for a store
        
        Args:
            store_id: The store ID
            scan_id: Optional scan ID to exclude (current scan)
            
        Returns:
            List of previous script tag snapshots
        """
        query = select(ScriptTagSnapshot).where(
            and_(
                ScriptTagSnapshot.store_id == store_id,
                ScriptTagSnapshot.is_removed == False
            )
        )
        
        if scan_id:
            query = query.where(ScriptTagSnapshot.scan_id != scan_id)
        
        query = query.order_by(ScriptTagSnapshot.last_seen.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_script_by_src(self, store_id: str, src: str) -> Optional[ScriptTagSnapshot]:
        """Get a script tag snapshot by its source URL"""
        result = await self.db.execute(
            select(ScriptTagSnapshot).where(
                and_(
                    ScriptTagSnapshot.store_id == store_id,
                    ScriptTagSnapshot.src == src,
                    ScriptTagSnapshot.is_removed == False
                )
            ).order_by(ScriptTagSnapshot.last_seen.desc()).limit(1)
        )
        return result.scalar_one_or_none()
    
    async def create_snapshot(
        self,
        store: Store,
        scan: DailyScan
    ) -> Dict[str, Any]:
        """
        Create a snapshot of all script tags and detect changes
        
        Args:
            store: The Store object
            scan: The DailyScan record to link snapshots to
            
        Returns:
            Summary of snapshot results
        """
        print(f"📸 [ScriptTag] Starting snapshot for {store.shopify_domain}")
        
        # Get current script tags from Shopify
        current_scripts = await self.get_script_tags(store)
        
        # Get previous script snapshots
        previous_snapshots = await self.get_previous_scripts(store.id)
        previous_srcs = {s.src: s for s in previous_snapshots}
        
        results = {
            "scripts_total": len(current_scripts),
            "scripts_new": 0,
            "scripts_removed": 0,
            "scripts_unchanged": 0,
            "apps_identified": []
        }
        
        current_srcs = set()
        
        # Process current scripts
        for script in current_scripts:
            src = script.get("src", "")
            current_srcs.add(src)
            
            shopify_id = str(script.get("id", ""))
            display_scope = script.get("display_scope", "")
            event = script.get("event", "onload")
            
            # Identify app
            likely_app = self.identify_app(src)
            if likely_app and likely_app not in results["apps_identified"]:
                results["apps_identified"].append(likely_app)
            
            # Check if this is a new script
            existing = previous_srcs.get(src)
            is_new = existing is None
            
            if is_new:
                results["scripts_new"] += 1
                
                # Create new snapshot
                snapshot = ScriptTagSnapshot(
                    store_id=store.id,
                    shopify_script_id=shopify_id,
                    src=src,
                    display_scope=display_scope,
                    event=event,
                    likely_app=likely_app,
                    is_new=True,
                    is_removed=False,
                    scan_id=scan.id,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow()
                )
                self.db.add(snapshot)
            else:
                results["scripts_unchanged"] += 1
                
                # Update last_seen on existing
                existing.last_seen = datetime.utcnow()
                existing.scan_id = scan.id
                existing.is_new = False
        
        # Check for removed scripts
        for src, snapshot in previous_srcs.items():
            if src not in current_srcs:
                results["scripts_removed"] += 1
                
                # Mark as removed
                snapshot.is_removed = True
                snapshot.scan_id = scan.id
        
        await self.db.flush()
        
        print(f"✅ [ScriptTag] Snapshot complete: {results}")
        return results
    
    async def get_script_history(
        self,
        store_id: str,
        limit: int = 50
    ) -> List[ScriptTagSnapshot]:
        """
        Get script tag history for a store
        
        Args:
            store_id: The store ID
            limit: Maximum number of records to return
            
        Returns:
            List of script tag snapshots ordered by first_seen desc
        """
        result = await self.db.execute(
            select(ScriptTagSnapshot)
            .where(ScriptTagSnapshot.store_id == store_id)
            .order_by(ScriptTagSnapshot.first_seen.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def get_new_scripts_since(
        self,
        store_id: str,
        since: datetime
    ) -> List[ScriptTagSnapshot]:
        """
        Get scripts added since a specific date
        
        Args:
            store_id: The store ID
            since: The datetime to check from
            
        Returns:
            List of new script tag snapshots
        """
        result = await self.db.execute(
            select(ScriptTagSnapshot)
            .where(
                and_(
                    ScriptTagSnapshot.store_id == store_id,
                    ScriptTagSnapshot.first_seen >= since,
                    ScriptTagSnapshot.is_new == True
                )
            )
            .order_by(ScriptTagSnapshot.first_seen.desc())
        )
        return result.scalars().all()
    
    async def get_removed_scripts_since(
        self,
        store_id: str,
        since: datetime
    ) -> List[ScriptTagSnapshot]:
        """
        Get scripts removed since a specific date
        
        Args:
            store_id: The store ID
            since: The datetime to check from
            
        Returns:
            List of removed script tag snapshots
        """
        result = await self.db.execute(
            select(ScriptTagSnapshot)
            .where(
                and_(
                    ScriptTagSnapshot.store_id == store_id,
                    ScriptTagSnapshot.is_removed == True,
                    ScriptTagSnapshot.last_seen >= since
                )
            )
            .order_by(ScriptTagSnapshot.last_seen.desc())
        )
        return result.scalars().all()