"""
Sherlock - Reported Apps Service
Manages community-reported problematic apps and Reddit discovery
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
import logging

from app.db.models import ReportedApp
from app.services.reddit_service import reddit_service

logger = logging.getLogger(__name__)


class ReportedAppsService:
    """Service for managing community-reported apps"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def report_app(
        self,
        app_name: str,
        shop: str,
        issue_type: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """
        Report an app as problematic
        
        1. Check if app already reported
        2. Fetch Reddit data
        3. Store/update in database
        4. Return findings
        """
        logger.info(f"📢 [ReportedApps] New report for '{app_name}' from {shop}")
        
        # Normalize app name
        app_name_normalized = app_name.strip()
        app_handle = app_name_normalized.lower().replace(" ", "-")
        
        # Check if already in database
        result = await self.db.execute(
            select(ReportedApp).where(
                func.lower(ReportedApp.app_name) == app_name_normalized.lower()
            )
        )
        existing = result.scalar_one_or_none()
        
        # Fetch fresh Reddit data
        reddit_data = await reddit_service.check_app_reputation(app_name_normalized)
        
        # Map issue type to boolean flags
        issue_flags = {
            "slowdown": "causes_slowdown",
            "slow": "causes_slowdown",
            "conflict": "causes_conflicts",
            "checkout": "causes_checkout_issues",
            "theme": "causes_theme_issues",
            "support": "poor_support",
        }
        
        if existing:
            # Update existing report
            existing.total_reports += 1
            existing.last_reported = datetime.utcnow()
            existing.reddit_risk_score = reddit_data.get("reddit_risk_score", 0)
            existing.reddit_posts_found = reddit_data.get("posts_found", 0)
            existing.reddit_sentiment = reddit_data.get("sentiment")
            existing.reddit_common_issues = reddit_data.get("common_issues", [])
            existing.reddit_sample_posts = reddit_data.get("sample_posts", [])[:5]
            existing.last_reddit_check = datetime.utcnow()
            
            # Update issue flags
            for key, field in issue_flags.items():
                if key in issue_type.lower():
                    setattr(existing, field, True)
            
            # Append to report reasons
            if existing.report_reasons is None:
                existing.report_reasons = []
            if description:
                existing.report_reasons = existing.report_reasons + [{
                    "shop": shop,
                    "issue_type": issue_type,
                    "description": description,
                    "reported_at": datetime.utcnow().isoformat()
                }]
            
            await self.db.flush()
            reported_app = existing
            is_new = False
            
        else:
            # Create new report
            reported_app = ReportedApp(
                app_name=app_name_normalized,
                app_handle=app_handle,
                reddit_risk_score=reddit_data.get("reddit_risk_score", 0),
                reddit_posts_found=reddit_data.get("posts_found", 0),
                reddit_sentiment=reddit_data.get("sentiment"),
                reddit_common_issues=reddit_data.get("common_issues", []),
                reddit_sample_posts=reddit_data.get("sample_posts", [])[:5],
                total_reports=1,
                report_reasons=[{
                    "shop": shop,
                    "issue_type": issue_type,
                    "description": description,
                    "reported_at": datetime.utcnow().isoformat()
                }] if description else [],
                last_reddit_check=datetime.utcnow()
            )
            
            # Set issue flags
            for key, field in issue_flags.items():
                if key in issue_type.lower():
                    setattr(reported_app, field, True)
            
            self.db.add(reported_app)
            await self.db.flush()
            is_new = True
        
        logger.info(f"✅ [ReportedApps] {'Created' if is_new else 'Updated'} report for '{app_name}'")
        
        return {
            "success": True,
            "is_new_report": is_new,
            "app_name": app_name_normalized,
            "total_reports": reported_app.total_reports,
            "reddit_data": {
                "risk_score": reddit_data.get("reddit_risk_score", 0),
                "posts_found": reddit_data.get("posts_found", 0),
                "sentiment": reddit_data.get("sentiment"),
                "common_issues": reddit_data.get("common_issues", [])[:5],
                "recommendation": reddit_data.get("recommendation", "")
            },
            "sample_posts": reddit_data.get("sample_posts", [])[:3]
        }
    
    async def get_reported_app(self, app_name: str) -> Optional[Dict[str, Any]]:
        """Get report data for a specific app"""
        result = await self.db.execute(
            select(ReportedApp).where(
                func.lower(ReportedApp.app_name) == app_name.lower()
            )
        )
        app = result.scalar_one_or_none()
        
        if not app:
            return None
        
        return self._app_to_dict(app)
    
    async def get_most_reported_apps(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get apps with the most reports"""
        result = await self.db.execute(
            select(ReportedApp)
            .where(ReportedApp.is_active == True)
            .order_by(ReportedApp.total_reports.desc())
            .limit(limit)
        )
        apps = result.scalars().all()
        
        return [self._app_to_dict(app) for app in apps]
    
    async def get_highest_risk_apps(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get apps with highest Reddit risk scores"""
        result = await self.db.execute(
            select(ReportedApp)
            .where(ReportedApp.is_active == True)
            .order_by(ReportedApp.reddit_risk_score.desc())
            .limit(limit)
        )
        apps = result.scalars().all()
        
        return [self._app_to_dict(app) for app in apps]
    
    async def get_recently_reported_apps(self, days: int = 7, limit: int = 20) -> List[Dict[str, Any]]:
        """Get apps reported in the last N days"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        result = await self.db.execute(
            select(ReportedApp)
            .where(ReportedApp.last_reported >= cutoff)
            .where(ReportedApp.is_active == True)
            .order_by(ReportedApp.last_reported.desc())
            .limit(limit)
        )
        apps = result.scalars().all()
        
        return [self._app_to_dict(app) for app in apps]
    
    async def check_app_in_reports(self, app_name: str) -> Optional[Dict[str, Any]]:
        """
        Check if an app is in our reported apps database
        Used during scans to add community data
        """
        result = await self.db.execute(
            select(ReportedApp).where(
                func.lower(ReportedApp.app_name) == app_name.lower()
            )
        )
        app = result.scalar_one_or_none()
        
        if not app:
            return None
        
        return {
            "is_reported": True,
            "total_reports": app.total_reports,
            "reddit_risk_score": app.reddit_risk_score,
            "reddit_sentiment": app.reddit_sentiment,
            "common_issues": app.reddit_common_issues,
            "issue_flags": {
                "causes_slowdown": app.causes_slowdown,
                "causes_conflicts": app.causes_conflicts,
                "causes_checkout_issues": app.causes_checkout_issues,
                "causes_theme_issues": app.causes_theme_issues,
                "poor_support": app.poor_support,
            }
        }
    
    async def discover_trending_issues(self) -> Dict[str, Any]:
        """
        Scan Reddit for trending Shopify app issues
        Automatically adds newly discovered problematic apps to database
        """
        logger.info("🔍 [ReportedApps] Discovering trending issues from Reddit...")
        
        # Get trending issues from Reddit
        trending = await reddit_service.get_trending_issues(limit=20)
        
        discovered_apps = []
        
        for post in trending.get("trending_issues", []):
            title = post.get("title", "").lower()
            
            # Try to extract app names from post titles
            # This is a simple approach - could be enhanced with NLP
            known_apps = [
                "pagefly", "gempages", "shogun", "klaviyo", "privy",
                "loox", "judge.me", "yotpo", "stamped", "omnisend",
                "recharge", "bold", "zipify", "vitals", "tidio",
                "gorgias", "aftership", "oberlo", "dsers", "weglot"
            ]
            
            for app in known_apps:
                if app in title:
                    # Check reputation and possibly add to database
                    reputation = await reddit_service.check_app_reputation(app)
                    
                    if reputation.get("reddit_risk_score", 0) >= 30:
                        # Add to database if not exists
                        await self._add_discovered_app(app, reputation, post)
                        discovered_apps.append({
                            "app_name": app,
                            "risk_score": reputation.get("reddit_risk_score", 0),
                            "source_post": post.get("title")
                        })
        
        logger.info(f"✅ [ReportedApps] Discovered {len(discovered_apps)} apps from trending issues")
        
        return {
            "discovered_count": len(discovered_apps),
            "discovered_apps": discovered_apps,
            "scanned_at": datetime.utcnow().isoformat()
        }
    
    async def _add_discovered_app(
        self,
        app_name: str,
        reputation: Dict,
        source_post: Dict
    ):
        """Add a discovered app to the database"""
        # Check if exists
        result = await self.db.execute(
            select(ReportedApp).where(
                func.lower(ReportedApp.app_name) == app_name.lower()
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update Reddit data if stale (> 24 hours)
            if existing.last_reddit_check:
                age = datetime.utcnow() - existing.last_reddit_check
                if age < timedelta(hours=24):
                    return  # Skip, data is fresh
            
            existing.reddit_risk_score = reputation.get("reddit_risk_score", 0)
            existing.reddit_posts_found = reputation.get("posts_found", 0)
            existing.reddit_sentiment = reputation.get("sentiment")
            existing.reddit_common_issues = reputation.get("common_issues", [])
            existing.last_reddit_check = datetime.utcnow()
            
        else:
            # Create new entry
            reported_app = ReportedApp(
                app_name=app_name.title(),
                app_handle=app_name.lower().replace(" ", "-"),
                reddit_risk_score=reputation.get("reddit_risk_score", 0),
                reddit_posts_found=reputation.get("posts_found", 0),
                reddit_sentiment=reputation.get("sentiment"),
                reddit_common_issues=reputation.get("common_issues", []),
                reddit_sample_posts=reputation.get("sample_posts", [])[:5],
                total_reports=0,  # Not user-reported, auto-discovered
                last_reddit_check=datetime.utcnow()
            )
            self.db.add(reported_app)
        
        await self.db.flush()
    
    async def refresh_all_reddit_data(self) -> Dict[str, Any]:
        """
        Refresh Reddit data for all reported apps
        Should be run periodically (e.g., daily)
        """
        logger.info("🔄 [ReportedApps] Refreshing Reddit data for all apps...")
        
        result = await self.db.execute(
            select(ReportedApp).where(ReportedApp.is_active == True)
        )
        apps = result.scalars().all()
        
        updated_count = 0
        
        for app in apps:
            try:
                reputation = await reddit_service.check_app_reputation(app.app_name)
                
                app.reddit_risk_score = reputation.get("reddit_risk_score", 0)
                app.reddit_posts_found = reputation.get("posts_found", 0)
                app.reddit_sentiment = reputation.get("sentiment")
                app.reddit_common_issues = reputation.get("common_issues", [])
                app.reddit_sample_posts = reputation.get("sample_posts", [])[:5]
                app.last_reddit_check = datetime.utcnow()
                
                updated_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to refresh {app.app_name}: {e}")
        
        await self.db.flush()
        
        logger.info(f"✅ [ReportedApps] Refreshed {updated_count} apps")
        
        return {
            "total_apps": len(apps),
            "updated_count": updated_count,
            "refreshed_at": datetime.utcnow().isoformat()
        }
    
    def _app_to_dict(self, app: ReportedApp) -> Dict[str, Any]:
        """Convert ReportedApp model to dictionary"""
        return {
            "id": app.id,
            "app_name": app.app_name,
            "app_handle": app.app_handle,
            "reddit_risk_score": app.reddit_risk_score,
            "reddit_posts_found": app.reddit_posts_found,
            "reddit_sentiment": app.reddit_sentiment,
            "reddit_common_issues": app.reddit_common_issues,
            "total_reports": app.total_reports,
            "issue_flags": {
                "causes_slowdown": app.causes_slowdown,
                "causes_conflicts": app.causes_conflicts,
                "causes_checkout_issues": app.causes_checkout_issues,
                "causes_theme_issues": app.causes_theme_issues,
                "poor_support": app.poor_support,
            },
            "is_verified": app.is_verified,
            "first_reported": app.first_reported.isoformat() if app.first_reported else None,
            "last_reported": app.last_reported.isoformat() if app.last_reported else None,
            "last_reddit_check": app.last_reddit_check.isoformat() if app.last_reddit_check else None,
        }