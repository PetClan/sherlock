"""
Sherlock - Daily Scan Service
Orchestrates daily monitoring scans: theme snapshots, script tracking, CSS risk detection
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.models import Store, DailyScan, ThemeFileVersion, ScriptTagSnapshot
from app.services.theme_snapshot_service import ThemeSnapshotService
from app.services.script_tag_service import ScriptTagService
from app.services.css_risk_service import CSSRiskService, CSSIssue


class DailyScanService:
    """Service for orchestrating daily monitoring scans"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.theme_service = ThemeSnapshotService(db)
        self.script_service = ScriptTagService(db)
        self.css_service = CSSRiskService()
    
    async def run_daily_scan(self, store: Store) -> DailyScan:
        """
        Run a full daily monitoring scan for a store
        
        Args:
            store: The Store object
            
        Returns:
            The DailyScan record with results
        """
        print(f"🔍 [DailyScan] Starting daily scan for {store.shopify_domain}")
        
        # Create scan record
        scan = DailyScan(
            store_id=store.id,
            scan_date=datetime.utcnow(),
            status="running"
        )
        self.db.add(scan)
        await self.db.flush()
        
        try:
            # Get active theme
            active_theme = await self.theme_service.get_active_theme(store)
            
            if not active_theme:
                scan.status = "failed"
                scan.error_message = "Could not find active theme"
                await self.db.flush()
                return scan
            
            theme_id = str(active_theme.get("id", ""))
            theme_name = active_theme.get("name", "Unknown")
            
            # 1. Theme file snapshot
            print(f"📸 [DailyScan] Taking theme snapshot...")
            theme_results = await self.theme_service.create_snapshot(
                store=store,
                theme_id=theme_id,
                theme_name=theme_name,
                scan=scan
            )
            
            # 2. Script tag snapshot
            print(f"📜 [DailyScan] Tracking script tags...")
            script_results = await self.script_service.create_snapshot(
                store=store,
                scan=scan
            )
            
            # 3. CSS risk detection on changed/new files
            print(f"🎨 [DailyScan] Scanning for CSS risks...")
            css_issues = await self._scan_css_risks(store.id, scan.id)
            css_risk = self.css_service.calculate_risk_score(css_issues)
            
            # Update scan with results
            scan.files_total = theme_results.get("files_total", 0)
            scan.files_changed = theme_results.get("files_changed", 0)
            scan.files_new = theme_results.get("files_new", 0)
            scan.files_deleted = 0  # TODO: implement deletion tracking
            
            scan.scripts_total = script_results.get("scripts_total", 0)
            scan.scripts_new = script_results.get("scripts_new", 0)
            scan.scripts_removed = script_results.get("scripts_removed", 0)
            
            scan.css_issues_found = len(css_issues)
            scan.non_namespaced_css = [
                {
                    "file": issue.file_path,
                    "selector": issue.selector,
                    "severity": issue.severity,
                    "description": issue.description
                }
                for issue in css_issues[:20]  # Limit to 20 issues stored
            ]
            
            # Calculate overall risk level
            risk_level, risk_reasons = self._calculate_risk_level(
                theme_results=theme_results,
                script_results=script_results,
                css_risk=css_risk
            )
            
            scan.risk_level = risk_level
            scan.risk_reasons = risk_reasons
            
            # Generate summary
            scan.summary = self._generate_summary(
                theme_results=theme_results,
                script_results=script_results,
                css_risk=css_risk,
                risk_level=risk_level
            )
            
            scan.scan_metadata = {
                "theme_id": theme_id,
                "theme_name": theme_name,
                "apps_identified": script_results.get("apps_identified", []),
                "app_owned_files": theme_results.get("app_owned_files", 0)
            }
            
            scan.status = "completed"
            scan.completed_at = datetime.utcnow()
            
            await self.db.flush()
            
            print(f"✅ [DailyScan] Scan complete: {risk_level} risk")
            return scan
            
        except Exception as e:
            print(f"❌ [DailyScan] Scan failed: {e}")
            scan.status = "failed"
            scan.error_message = str(e)
            scan.completed_at = datetime.utcnow()
            await self.db.flush()
            return scan
    
    async def _scan_css_risks(self, store_id: str, scan_id: str) -> List[CSSIssue]:
        """
        Scan CSS files from the current scan for risks
        
        Args:
            store_id: The store ID
            scan_id: The current scan ID
            
        Returns:
            List of CSSIssue objects
        """
        all_issues = []
        
        # Get theme files from this scan that are CSS or Liquid
        result = await self.db.execute(
            select(ThemeFileVersion).where(
                and_(
                    ThemeFileVersion.store_id == store_id,
                    ThemeFileVersion.scan_id == scan_id
                )
            )
        )
        files = result.scalars().all()
        
        for file in files:
            # Only scan CSS files and Liquid files that might contain CSS
            if file.file_path.endswith('.css') or file.file_path.endswith('.liquid'):
                if file.content:
                    issues = self.css_service.scan_theme_file(
                        content=file.content,
                        file_path=file.file_path
                    )
                    all_issues.extend(issues)
        
        return all_issues
    
    def _calculate_risk_level(
        self,
        theme_results: Dict[str, Any],
        script_results: Dict[str, Any],
        css_risk: Dict[str, Any]
    ) -> tuple[str, List[str]]:
        """
        Calculate overall risk level from scan results
        
        Returns:
            Tuple of (risk_level, risk_reasons)
        """
        risk_reasons = []
        risk_score = 0
        
        # Theme file changes
        files_changed = theme_results.get("files_changed", 0)
        files_new = theme_results.get("files_new", 0)
        
        if files_changed > 10:
            risk_score += 30
            risk_reasons.append(f"{files_changed} theme files changed")
        elif files_changed > 5:
            risk_score += 20
            risk_reasons.append(f"{files_changed} theme files changed")
        elif files_changed > 0:
            risk_score += 10
            risk_reasons.append(f"{files_changed} theme files changed")
        
        if files_new > 5:
            risk_score += 20
            risk_reasons.append(f"{files_new} new files added")
        elif files_new > 0:
            risk_score += 10
            risk_reasons.append(f"{files_new} new files added")
        
        # Script changes
        scripts_new = script_results.get("scripts_new", 0)
        scripts_removed = script_results.get("scripts_removed", 0)
        
        if scripts_new > 0:
            risk_score += 15 * scripts_new
            risk_reasons.append(f"{scripts_new} new scripts injected")
        
        if scripts_removed > 0:
            risk_score += 5
            risk_reasons.append(f"{scripts_removed} scripts removed")
        
        # CSS risks
        css_level = css_risk.get("level", "low")
        if css_level == "high":
            risk_score += 30
            risk_reasons.append(f"High CSS conflict risk ({css_risk.get('total_issues', 0)} issues)")
        elif css_level == "medium":
            risk_score += 15
            risk_reasons.append(f"Medium CSS conflict risk ({css_risk.get('total_issues', 0)} issues)")
        
        # Determine level
        if risk_score >= 50:
            risk_level = "high"
        elif risk_score >= 25:
            risk_level = "medium"
        else:
            risk_level = "low"
        
        if not risk_reasons:
            risk_reasons.append("No significant changes detected")
        
        return risk_level, risk_reasons
    
    def _generate_summary(
        self,
        theme_results: Dict[str, Any],
        script_results: Dict[str, Any],
        css_risk: Dict[str, Any],
        risk_level: str
    ) -> str:
        """
        Generate a human-readable summary of the scan
        
        Returns:
            Summary string
        """
        parts = []
        
        # Risk level header
        if risk_level == "high":
            parts.append("⚠️ HIGH RISK: Significant changes detected that may affect your store.")
        elif risk_level == "medium":
            parts.append("⚡ MEDIUM RISK: Some changes detected that you should review.")
        else:
            parts.append("✅ LOW RISK: No significant changes detected.")
        
        # Theme changes
        files_changed = theme_results.get("files_changed", 0)
        files_new = theme_results.get("files_new", 0)
        files_total = theme_results.get("files_total", 0)
        
        if files_changed > 0 or files_new > 0:
            parts.append(f"Theme: {files_changed} files changed, {files_new} new files (out of {files_total} total).")
        else:
            parts.append(f"Theme: No changes to {files_total} files.")
        
        # Script changes
        scripts_new = script_results.get("scripts_new", 0)
        scripts_removed = script_results.get("scripts_removed", 0)
        scripts_total = script_results.get("scripts_total", 0)
        
        if scripts_new > 0 or scripts_removed > 0:
            parts.append(f"Scripts: {scripts_new} new, {scripts_removed} removed ({scripts_total} total).")
        else:
            parts.append(f"Scripts: No changes ({scripts_total} active).")
        
        # CSS risks
        css_issues = css_risk.get("total_issues", 0)
        if css_issues > 0:
            parts.append(f"CSS: {css_issues} potential conflict issues found.")
        
        # App-owned files
        app_files = theme_results.get("app_owned_files", 0)
        if app_files > 0:
            parts.append(f"App files: {app_files} files appear to belong to third-party apps.")
        
        return " ".join(parts)
    
    async def get_latest_scan(self, store_id: str) -> Optional[DailyScan]:
        """Get the most recent scan for a store"""
        result = await self.db.execute(
            select(DailyScan)
            .where(DailyScan.store_id == store_id)
            .order_by(DailyScan.scan_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def get_scan_history(
        self,
        store_id: str,
        limit: int = 30
    ) -> List[DailyScan]:
        """Get scan history for a store"""
        result = await self.db.execute(
            select(DailyScan)
            .where(DailyScan.store_id == store_id)
            .order_by(DailyScan.scan_date.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def get_high_risk_scans(
        self,
        store_id: str,
        limit: int = 10
    ) -> List[DailyScan]:
        """Get recent high-risk scans for a store"""
        result = await self.db.execute(
            select(DailyScan)
            .where(
                and_(
                    DailyScan.store_id == store_id,
                    DailyScan.risk_level == "high"
                )
            )
            .order_by(DailyScan.scan_date.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def get_changed_files_for_scan(
        self,
        scan_id: str
    ) -> List[ThemeFileVersion]:
        """Get files that changed in a specific scan"""
        result = await self.db.execute(
            select(ThemeFileVersion)
            .where(
                and_(
                    ThemeFileVersion.scan_id == scan_id,
                    ThemeFileVersion.is_changed == True
                )
            )
            .order_by(ThemeFileVersion.file_path)
        )
        return result.scalars().all()
    
    async def get_new_files_for_scan(
        self,
        scan_id: str
    ) -> List[ThemeFileVersion]:
        """Get new files added in a specific scan"""
        result = await self.db.execute(
            select(ThemeFileVersion)
            .where(
                and_(
                    ThemeFileVersion.scan_id == scan_id,
                    ThemeFileVersion.is_new == True
                )
            )
            .order_by(ThemeFileVersion.file_path)
        )
        return result.scalars().all()
    
    async def get_new_scripts_for_scan(
        self,
        scan_id: str
    ) -> List[ScriptTagSnapshot]:
        """Get new scripts added in a specific scan"""
        result = await self.db.execute(
            select(ScriptTagSnapshot)
            .where(
                and_(
                    ScriptTagSnapshot.scan_id == scan_id,
                    ScriptTagSnapshot.is_new == True
                )
            )
        )
        return result.scalars().all()