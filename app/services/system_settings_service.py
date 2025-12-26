"""
Sherlock - System Settings Service
Manages kill switches, rate limits, and system-wide settings
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from typing import Optional

from app.db.models import SystemSettings


# Default settings that will be initialized on first run
DEFAULT_SETTINGS = {
    "scanning_enabled": {
        "value": "true",
        "description": "Master kill switch - set to 'false' to pause ALL scanning"
    },
    "restores_enabled": {
        "value": "true",
        "description": "Read-only mode - set to 'false' to disable ALL theme restores"
    },
    "daily_scans_enabled": {
        "value": "true",
        "description": "Daily scheduled scans - set to 'false' to pause automated scans"
    },
    "max_on_demand_scans_per_day": {
        "value": "5",
        "description": "Maximum on-demand scans per store per day"
    },
    "max_restores_per_day": {
        "value": "3",
        "description": "Maximum theme restores per store per day"
    },
    "api_rate_limit_buffer": {
        "value": "20",
        "description": "Percentage buffer before Shopify API limit (e.g., 20 = stop at 80% usage)"
    }
}


class SystemSettingsService:
    """Service for managing system-wide settings and kill switches"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def initialize_defaults(self) -> dict:
        """
        Initialize default settings if they don't exist.
        Call this on app startup.
        Returns dict of settings that were created.
        """
        created = {}
        
        for key, config in DEFAULT_SETTINGS.items():
            existing = await self.get_setting(key)
            if existing is None:
                await self.set_setting(
                    key=key,
                    value=config["value"],
                    description=config["description"],
                    updated_by="system_init"
                )
                created[key] = config["value"]
                print(f"  ✅ Initialized setting: {key} = {config['value']}")
        
        return created
    
    async def get_setting(self, key: str) -> Optional[str]:
        """Get a setting value by key. Returns None if not found."""
        result = await self.db.execute(
            select(SystemSettings).where(SystemSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        return setting.value if setting else None
    
    async def get_setting_bool(self, key: str, default: bool = True) -> bool:
        """Get a setting as a boolean. Returns default if not found."""
        value = await self.get_setting(key)
        if value is None:
            return default
        return value.lower() in ("true", "1", "yes", "on")
    
    async def get_setting_int(self, key: str, default: int = 0) -> int:
        """Get a setting as an integer. Returns default if not found or invalid."""
        value = await self.get_setting(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default
    
    async def set_setting(
        self, 
        key: str, 
        value: str, 
        description: Optional[str] = None,
        updated_by: Optional[str] = None
    ) -> SystemSettings:
        """Set a setting value. Creates if doesn't exist, updates if it does."""
        result = await self.db.execute(
            select(SystemSettings).where(SystemSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting:
            # Update existing
            setting.value = value
            setting.updated_at = datetime.utcnow()
            if updated_by:
                setting.updated_by = updated_by
            if description:
                setting.description = description
        else:
            # Create new
            setting = SystemSettings(
                key=key,
                value=value,
                description=description,
                updated_by=updated_by
            )
            self.db.add(setting)
        
        await self.db.flush()
        return setting
    
    async def get_all_settings(self) -> dict:
        """Get all settings as a dictionary."""
        result = await self.db.execute(select(SystemSettings))
        settings = result.scalars().all()
        return {s.key: {"value": s.value, "description": s.description, "updated_at": s.updated_at, "updated_by": s.updated_by} for s in settings}
    
    # ==================== Convenience Methods ====================
    
    async def is_scanning_enabled(self) -> bool:
        """Check if scanning is enabled (master kill switch)"""
        return await self.get_setting_bool("scanning_enabled", default=True)
    
    async def is_restores_enabled(self) -> bool:
        """Check if restores are enabled (read-only mode check)"""
        return await self.get_setting_bool("restores_enabled", default=True)
    
    async def is_daily_scans_enabled(self) -> bool:
        """Check if daily automated scans are enabled"""
        return await self.get_setting_bool("daily_scans_enabled", default=True)
    
    async def get_max_on_demand_scans(self) -> int:
        """Get max on-demand scans per store per day"""
        return await self.get_setting_int("max_on_demand_scans_per_day", default=5)
    
    async def get_max_restores(self) -> int:
        """Get max restores per store per day"""
        return await self.get_setting_int("max_restores_per_day", default=10)