"""
Sherlock - Usage Limit Service
Tracks and enforces per-store daily usage limits
"""

from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.db.models import StoreDailyUsage, Store
from app.services.system_settings_service import SystemSettingsService

# Try to import zoneinfo (Python 3.9+), fall back to pytz
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from pytz import timezone as ZoneInfo


class UsageLimitService:
    """Service for tracking and enforcing usage limits"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings_service = SystemSettingsService(db)
    
    def _get_today(self, store_timezone: Optional[str] = None) -> str:
        """Get today's date in YYYY-MM-DD format in store's timezone"""
        if store_timezone:
            try:
                tz = ZoneInfo(store_timezone)
                return datetime.now(tz).strftime("%Y-%m-%d")
            except Exception:
                pass  # Fall back to UTC if timezone is invalid
        
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    async def _get_store_timezone(self, store_id: str) -> Optional[str]:
        """Get the timezone for a store"""
        result = await self.db.execute(
            select(Store.timezone).where(Store.id == store_id)
        )
        return result.scalar_one_or_none()
    
    async def _get_or_create_usage(self, store_id: str) -> StoreDailyUsage:
        """Get or create today's usage record for a store"""
        store_timezone = await self._get_store_timezone(store_id)
        today = self._get_today(store_timezone)
        
        result = await self.db.execute(
            select(StoreDailyUsage).where(
                StoreDailyUsage.store_id == store_id,
                StoreDailyUsage.usage_date == today
            )
        )
        usage = result.scalar_one_or_none()
        
        if not usage:
            usage = StoreDailyUsage(
                store_id=store_id,
                usage_date=today,
                scan_count=0,
                restore_count=0
            )
            self.db.add(usage)
            await self.db.flush()
        
        return usage
    
    async def can_scan(self, store_id: str) -> dict:
        """
        Check if store can perform an on-demand scan today.
        Returns dict with 'allowed', 'current', 'limit', and 'message'.
        """
        usage = await self._get_or_create_usage(store_id)
        limit = await self.settings_service.get_max_on_demand_scans()
        
        if usage.scan_count >= limit:
            return {
                "allowed": False,
                "current": usage.scan_count,
                "limit": limit,
                "message": f"Daily scan limit reached ({limit} scans per day). Resets at midnight in your store's timezone."
            }
        
        return {
            "allowed": True,
            "current": usage.scan_count,
            "limit": limit,
            "remaining": limit - usage.scan_count
        }
    
    async def can_restore(self, store_id: str) -> dict:
        """
        Check if store can perform a restore today.
        Returns dict with 'allowed', 'current', 'limit', and 'message'.
        """
        usage = await self._get_or_create_usage(store_id)
        limit = await self.settings_service.get_max_restores()
        
        if usage.restore_count >= limit:
            return {
                "allowed": False,
                "current": usage.restore_count,
                "limit": limit,
                "message": f"Daily restore limit reached ({limit} restores per day). Resets at midnight in your store's timezone."
            }
        
        return {
            "allowed": True,
            "current": usage.restore_count,
            "limit": limit,
            "remaining": limit - usage.restore_count
        }
    
    async def record_scan(self, store_id: str) -> StoreDailyUsage:
        """Record a scan was performed. Call AFTER successful scan."""
        usage = await self._get_or_create_usage(store_id)
        usage.scan_count += 1
        usage.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return usage
    
    async def record_restore(self, store_id: str) -> StoreDailyUsage:
        """Record a restore was performed. Call AFTER successful restore."""
        usage = await self._get_or_create_usage(store_id)
        usage.restore_count += 1
        usage.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return usage
    
    async def get_usage(self, store_id: str) -> dict:
        """Get current usage stats for a store"""
        usage = await self._get_or_create_usage(store_id)
        scan_limit = await self.settings_service.get_max_on_demand_scans()
        restore_limit = await self.settings_service.get_max_restores()
        
        return {
            "date": usage.usage_date,
            "scans": {
                "used": usage.scan_count,
                "limit": scan_limit,
                "remaining": max(0, scan_limit - usage.scan_count)
            },
            "restores": {
                "used": usage.restore_count,
                "limit": restore_limit,
                "remaining": max(0, restore_limit - usage.restore_count)
            }
        }