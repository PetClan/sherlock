"""
Sherlock - Data Retention Service
Auto-prunes old theme snapshots based on store plan tier
"""

from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, and_

from app.db.models import Store, ThemeFileVersion, DailyScan, ScriptTagSnapshot


# Retention days per plan
PLAN_RETENTION_DAYS = {
    "standard": 7,
    "professional": 30,
}

DEFAULT_RETENTION_DAYS = 7


class DataRetentionService:
    """Service for managing data retention and cleanup"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    def get_retention_days(self, plan: str) -> int:
        """Get retention days for a plan tier"""
        return PLAN_RETENTION_DAYS.get(plan, DEFAULT_RETENTION_DAYS)
    
    async def prune_store_data(self, store: Store) -> dict:
        """
        Prune old data for a single store based on their plan
        
        Returns:
            Dict with counts of deleted records
        """
        retention_days = self.get_retention_days(store.sherlock_plan or "standard")
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        results = {
            "store": store.shopify_domain,
            "plan": store.sherlock_plan or "standard",
            "retention_days": retention_days,
            "cutoff_date": cutoff_date.isoformat(),
            "theme_files_deleted": 0,
            "scans_deleted": 0,
            "script_snapshots_deleted": 0,
        }
        
        try:
            # Delete old theme file versions
            theme_result = await self.db.execute(
                delete(ThemeFileVersion).where(
                    and_(
                        ThemeFileVersion.store_id == store.id,
                        ThemeFileVersion.created_at < cutoff_date
                    )
                )
            )
            results["theme_files_deleted"] = theme_result.rowcount
            
            # Delete old daily scans
            scan_result = await self.db.execute(
                delete(DailyScan).where(
                    and_(
                        DailyScan.store_id == store.id,
                        DailyScan.scan_date < cutoff_date
                    )
                )
            )
            results["scans_deleted"] = scan_result.rowcount
            
            # Delete old script tag snapshots
            script_result = await self.db.execute(
                delete(ScriptTagSnapshot).where(
                    and_(
                        ScriptTagSnapshot.store_id == store.id,
                        ScriptTagSnapshot.created_at < cutoff_date
                    )
                )
            )
            results["script_snapshots_deleted"] = script_result.rowcount
            
            await self.db.flush()
            
        except Exception as e:
            results["error"] = str(e)
        
        return results
    
    async def prune_all_stores(self) -> dict:
        """
        Prune old data for all active stores
        
        Returns:
            Summary of all deletions
        """
        result = await self.db.execute(
            select(Store).where(Store.is_active == True)
        )
        stores = result.scalars().all()
        
        summary = {
            "stores_processed": 0,
            "total_theme_files_deleted": 0,
            "total_scans_deleted": 0,
            "total_script_snapshots_deleted": 0,
            "errors": [],
            "details": []
        }
        
        for store in stores:
            store_result = await self.prune_store_data(store)
            summary["stores_processed"] += 1
            summary["total_theme_files_deleted"] += store_result.get("theme_files_deleted", 0)
            summary["total_scans_deleted"] += store_result.get("scans_deleted", 0)
            summary["total_script_snapshots_deleted"] += store_result.get("script_snapshots_deleted", 0)
            
            if store_result.get("error"):
                summary["errors"].append({
                    "store": store.shopify_domain,
                    "error": store_result["error"]
                })
            
            # Only include in details if something was deleted
            if (store_result.get("theme_files_deleted", 0) > 0 or 
                store_result.get("scans_deleted", 0) > 0 or
                store_result.get("script_snapshots_deleted", 0) > 0):
                summary["details"].append(store_result)
        
        return summary
    
    async def get_storage_stats(self) -> dict:
        """Get storage statistics for admin dashboard"""
        
        # Total records per table
        theme_count = await self.db.execute(
            select(func.count(ThemeFileVersion.id))
        )
        scan_count = await self.db.execute(
            select(func.count(DailyScan.id))
        )
        script_count = await self.db.execute(
            select(func.count(ScriptTagSnapshot.id))
        )
        
        # Records by plan
        stores_by_plan = await self.db.execute(
            select(
                Store.sherlock_plan,
                func.count(Store.id)
            ).where(Store.is_active == True)
            .group_by(Store.sherlock_plan)
        )
        
        plan_breakdown = {row[0] or "standard": row[1] for row in stores_by_plan}
        
        return {
            "total_theme_file_versions": theme_count.scalar() or 0,
            "total_daily_scans": scan_count.scalar() or 0,
            "total_script_snapshots": script_count.scalar() or 0,
            "stores_by_plan": plan_breakdown
        }