"""
Sherlock - Issue Correlation Service
Matches detected issues to likely app culprits based on timing
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_

from app.db.models import Store, InstalledApp, ThemeIssue, DailyScan
from app.services.conflict_database import ConflictDatabase


class IssueCorrelationService:
    """
    Correlates detected issues with recently installed apps
    to help merchants identify the likely cause
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_store_diagnosis(self, shop_domain: str) -> Dict[str, Any]:
        """
        Get a full diagnosis for a store including:
        - Current issues
        - Likely culprits
        - Recommended actions
        """
        # Get store
        result = await self.db.execute(
            select(Store).where(Store.shopify_domain == shop_domain)
        )
        store = result.scalar_one_or_none()
        
        if not store:
            return {
                "shop": shop_domain,
                "status": "unknown",
                "message": "Store not found"
            }
        
        # Get unresolved issues
        issues = await self._get_unresolved_issues(store.id)
        
        # Get recently installed apps (last 14 days)
        recent_apps = await self._get_recent_apps(store.id, days=14)
        
        # Get last clean scan
        last_clean_scan = await self._get_last_clean_scan(store.id)
        
        # If no issues, store is healthy
        if not issues:
            return {
                "shop": shop_domain,
                "status": "healthy",
                "message": "No issues detected. Your store is running smoothly.",
                "issues": [],
                "suspects": [],
                "last_clean_scan": last_clean_scan.isoformat() if last_clean_scan else None
            }
        
        # Get all installed apps for conflict checking
        all_apps = await self._get_all_installed_apps(store.id)
        all_app_names = [app.app_name for app in all_apps]
        
        # Check for conflicts between installed apps
        conflict_db = ConflictDatabase()
        conflicts = conflict_db.check_conflicts(all_app_names)
        
        # Correlate issues with apps
        correlations = self._correlate_issues_to_apps(issues, recent_apps, last_clean_scan)
        
        # Build merchant-friendly diagnosis
        diagnosis = self._build_diagnosis(issues, correlations, recent_apps, conflicts, all_app_names)
        
        return {
            "shop": shop_domain,
            "status": "issues_found",
            "issue_count": len(issues),
            "issues": diagnosis["issues"],
            "primary_suspect": diagnosis["primary_suspect"],
            "all_suspects": diagnosis["all_suspects"],
            "recommended_actions": diagnosis["actions"],
            "last_clean_scan": last_clean_scan.isoformat() if last_clean_scan else None,
            "apps_since_clean": len(recent_apps)
        }
    
    async def _get_unresolved_issues(self, store_id: str) -> List[ThemeIssue]:
        """Get all unresolved issues for a store"""
        result = await self.db.execute(
            select(ThemeIssue)
            .where(ThemeIssue.store_id == store_id)
            .where(ThemeIssue.is_resolved == False)
            .order_by(desc(ThemeIssue.detected_at))
        )
        return result.scalars().all()
    
    async def _get_all_installed_apps(self, store_id: str) -> List[InstalledApp]:
        """Get all installed apps for a store"""
        result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store_id)
        )
        return result.scalars().all()

    async def _get_recent_apps(self, store_id: str, days: int = 14) -> List[InstalledApp]:
        """Get apps installed OR updated in the last N days"""
        since = datetime.utcnow() - timedelta(days=days)
        
        # Get apps installed recently
        installed_result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store_id)
            .where(InstalledApp.installed_on >= since)
        )
        installed_apps = installed_result.scalars().all()
        
        # Get apps updated recently
        updated_result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store_id)
            .where(InstalledApp.update_detected_at >= since)
        )
        updated_apps = updated_result.scalars().all()
        
        # Combine and deduplicate
        all_apps = {app.id: app for app in installed_apps}
        for app in updated_apps:
            if app.id not in all_apps:
                all_apps[app.id] = app
        
        # Sort by most recent activity (install or update)
        def get_latest_date(app):
            dates = [d for d in [app.installed_on, app.update_detected_at] if d]
            return max(dates) if dates else datetime.min
        
        return sorted(all_apps.values(), key=get_latest_date, reverse=True)
    
    async def _get_last_clean_scan(self, store_id: str) -> Optional[datetime]:
        """Get the date of the last scan with no issues"""
        result = await self.db.execute(
            select(DailyScan)
            .where(DailyScan.store_id == store_id)
            .where(DailyScan.risk_level == "low")
            .where(DailyScan.css_issues_found == 0)
            .order_by(desc(DailyScan.scan_date))
            .limit(1)
        )
        scan = result.scalar_one_or_none()
        return scan.scan_date if scan else None
    
    def _correlate_issues_to_apps(
        self, 
        issues: List[ThemeIssue], 
        apps: List[InstalledApp],
        last_clean: Optional[datetime]
    ) -> Dict[str, Dict]:
        """
        Match issues to apps based on timing
        Returns dict of app_name -> {confidence, issues_caused, reasoning}
        """
        correlations = {}
        
        for issue in issues:
            issue_date = issue.detected_at
            
            # If issue already has attribution, use it
            if issue.likely_source:
                app_name = issue.likely_source
                if app_name not in correlations:
                    correlations[app_name] = {
                        "confidence": issue.confidence or 50,
                        "issues_caused": [],
                        "reasoning": "Previously identified as likely source",
                        "installed_on": None,
                        "updated_on": None,
                        "was_updated": False
                    }
                correlations[app_name]["issues_caused"].append({
                    "type": issue.issue_type,
                    "file": issue.file_path,
                    "severity": issue.severity
                })
                continue
            
            # Otherwise, look for apps installed or updated before issue was detected
            for app in apps:
                # Determine if this was an install or update
                was_updated = False
                relevant_date = None
                
                # Check if app was updated recently
                if app.update_detected_at and app.update_detected_at <= issue_date:
                    # If update is more recent than install, it's likely the cause
                    if not app.installed_on or app.update_detected_at > app.installed_on:
                        was_updated = True
                        relevant_date = app.update_detected_at
                
                # If not an update, check install date
                if not relevant_date and app.installed_on and app.installed_on <= issue_date:
                    relevant_date = app.installed_on
                
                if not relevant_date:
                    continue
                
                # Calculate time gap
                gap = (issue_date - relevant_date).days
                
                # Closer in time = higher confidence
                if gap <= 1:
                    confidence = 85
                    if was_updated:
                        reasoning = "Updated 1 day before issue appeared"
                    else:
                        reasoning = "Installed 1 day before issue appeared"
                elif gap <= 3:
                    confidence = 70
                    if was_updated:
                        reasoning = f"Updated {gap} days before issue appeared"
                    else:
                        reasoning = f"Installed {gap} days before issue appeared"
                elif gap <= 7:
                    confidence = 50
                    if was_updated:
                        reasoning = f"Updated {gap} days before issue appeared"
                    else:
                        reasoning = f"Installed {gap} days before issue appeared"
                else:
                    confidence = 30
                    if was_updated:
                        reasoning = f"Updated {gap} days ago"
                    else:
                        reasoning = f"Installed {gap} days ago"
                
                # Boost confidence if app is flagged as suspect
                if app.is_suspect:
                    confidence = min(95, confidence + 15)
                    reasoning += " (flagged as potentially problematic)"
                
                # Add note about update being potential cause
                if was_updated:
                    reasoning += " - app updates can introduce new issues"
                
                app_name = app.app_name
                if app_name not in correlations:
                    correlations[app_name] = {
                        "confidence": confidence,
                        "issues_caused": [],
                        "reasoning": reasoning,
                        "installed_on": app.installed_on.isoformat() if app.installed_on else None,
                        "updated_on": app.update_detected_at.isoformat() if app.update_detected_at else None,
                        "was_updated": was_updated
                    }
                else:
                    # Update confidence if this correlation is stronger
                    if confidence > correlations[app_name]["confidence"]:
                        correlations[app_name]["confidence"] = confidence
                        correlations[app_name]["reasoning"] = reasoning
                        correlations[app_name]["was_updated"] = was_updated
                
                correlations[app_name]["issues_caused"].append({
                    "type": issue.issue_type,
                    "file": issue.file_path,
                    "severity": issue.severity
                })
        
        return correlations
    
    def _build_diagnosis(
        self, 
        issues: List[ThemeIssue], 
        correlations: Dict[str, Dict],
        recent_apps: List[InstalledApp],
        conflicts: List[Dict] = None,
        all_app_names: List[str] = None
    ) -> Dict[str, Any]:
        """Build merchant-friendly diagnosis with clear actions"""
        
        conflicts = conflicts or []
        all_app_names = all_app_names or []
        
        # Format issues for display
        formatted_issues = []
        for issue in issues:
            formatted_issues.append({
                "type": issue.issue_type,
                "severity": issue.severity,
                "file": issue.file_path,
                "description": self._get_issue_description(issue),
                "detected_at": issue.detected_at.isoformat() if issue.detected_at else None
            })
        
        # Sort suspects by confidence
        suspects = []
        for app_name, data in correlations.items():
            # Check if this app has conflicts with other installed apps
            app_conflicts = self._get_app_conflicts(app_name, conflicts)
            
            suspects.append({
                "app_name": app_name,
                "confidence": data["confidence"],
                "confidence_label": self._get_confidence_label(data["confidence"]),
                "reasoning": data["reasoning"],
                "issues_caused": len(data["issues_caused"]),
                "installed_on": data["installed_on"],
                "was_updated": data.get("was_updated", False),
                "conflicts_with": app_conflicts
            })
        
        suspects.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Determine primary suspect
        primary_suspect = None
        if suspects:
            top = suspects[0]
            primary_suspect = {
                "app_name": top["app_name"],
                "confidence": top["confidence"],
                "confidence_label": top["confidence_label"],
                "message": self._get_suspect_message(top),
                "was_updated": top["was_updated"],
                "conflicts_with": top["conflicts_with"]
            }
        
        # Build recommended actions
        actions = self._build_actions(primary_suspect, suspects, issues, conflicts)
        
        return {
            "issues": formatted_issues,
            "primary_suspect": primary_suspect,
            "all_suspects": suspects,
            "actions": actions,
            "conflicts": conflicts
        }
    
    def _get_app_conflicts(self, app_name: str, conflicts: List[Dict]) -> List[Dict]:
        """Get conflicts involving this specific app"""
        app_conflicts = []
        app_lower = app_name.lower()
        
        for conflict in conflicts:
            matched = [a.lower() for a in conflict.get("matched_apps", [])]
            if app_lower in matched or any(app_lower in m for m in matched):
                # Find the OTHER app in the conflict
                other_apps = [a for a in conflict.get("conflicting_apps", []) 
                             if a.lower() != app_lower and app_lower not in a.lower()]
                if other_apps:
                    app_conflicts.append({
                        "other_app": other_apps[0],
                        "severity": conflict.get("severity"),
                        "description": conflict.get("description"),
                        "solution": conflict.get("solution")
                    })
        
        return app_conflicts
    
    def _get_issue_description(self, issue: ThemeIssue) -> str:
        """Get plain English description of an issue"""
        descriptions = {
            "injected_script": "Unknown code was added to your theme files",
            "duplicate_code": "The same code appears multiple times, which can slow your store",
            "conflict": "Two apps are trying to modify the same part of your theme",
            "error": "There's a code error that could break parts of your store",
            "css_conflict": "Styling code is conflicting, which may affect how your store looks",
            "global_css": "An app added styling that could affect your entire store's appearance"
        }
        return descriptions.get(issue.issue_type, f"A {issue.issue_type} issue was detected")
    
    def _get_confidence_label(self, confidence: float) -> str:
        """Convert confidence score to plain English"""
        if confidence >= 80:
            return "Very likely"
        elif confidence >= 60:
            return "Likely"
        elif confidence >= 40:
            return "Possibly"
        else:
            return "Uncertain"
    
    def _get_suspect_message(self, suspect: Dict) -> str:
        """Build a clear message about the suspected app"""
        confidence = suspect["confidence"]
        app = suspect["app_name"]
        
        if confidence >= 80:
            return f"'{app}' is very likely causing the issue. It was {suspect['reasoning'].lower()}."
        elif confidence >= 60:
            return f"'{app}' is likely the cause. It was {suspect['reasoning'].lower()}."
        elif confidence >= 40:
            return f"'{app}' may be involved. It was {suspect['reasoning'].lower()}."
        else:
            return f"'{app}' could possibly be related, but we're not certain."
    
    def _build_actions(
        self, 
        primary: Optional[Dict], 
        suspects: List[Dict], 
        issues: List[ThemeIssue],
        conflicts: List[Dict] = None
    ) -> List[Dict]:
        """Build step-by-step actions for the merchant"""
        actions = []
        conflicts = conflicts or []
        
        if primary and primary["confidence"] >= 60:
            # Check if there's a conflict with another app
            if primary.get("conflicts_with"):
                conflict = primary["conflicts_with"][0]
                other_app = conflict["other_app"]
                
                # Conflict-based guidance
                actions.append({
                    "step": 1,
                    "title": f"'{primary['app_name']}' may be conflicting with '{other_app}'",
                    "description": f"{conflict['description']}",
                    "why": "These two apps are known to cause issues when used together."
                })
                actions.append({
                    "step": 2,
                    "title": f"Try disabling '{primary['app_name']}' first",
                    "description": f"Go to your Shopify admin → Apps, find '{primary['app_name']}', and disable it. Check if your store works normally.",
                    "why": f"Since '{primary['app_name']}' was installed more recently, it's the more likely culprit."
                })
                actions.append({
                    "step": 3,
                    "title": "If that doesn't fix it, try the other app",
                    "description": f"Re-enable '{primary['app_name']}', then disable '{other_app}' instead. Check your store again.",
                    "why": "Sometimes the older app is actually the problem, especially after updates."
                })
                actions.append({
                    "step": 4,
                    "title": "Consider replacing one of them",
                    "description": f"{conflict.get('solution', 'You may need to choose one app over the other.')}",
                    "why": "Some apps simply can't work together. Choosing one should permanently fix the issue."
                })
            elif primary.get("was_updated", False):
                # Update-specific guidance
                actions.append({
                    "step": 1,
                    "title": f"'{primary['app_name']}' was recently updated",
                    "description": "This app received an update around the time your issue started. Updates can sometimes introduce new bugs or conflicts.",
                    "why": "The timing of the update matches when the problem appeared."
                })
                actions.append({
                    "step": 2,
                    "title": "Check if you can roll back the app",
                    "description": f"Some apps let you use a previous version. Check '{primary['app_name']}' settings or contact their support.",
                    "why": "Rolling back to the previous version may fix the issue immediately."
                })
                actions.append({
                    "step": 3,
                    "title": "If no rollback, disable temporarily",
                    "description": f"Go to your Shopify admin → Apps, find '{primary['app_name']}', and disable it. Check if your store works normally.",
                    "why": "This confirms whether the updated app is causing the problem."
                })
                actions.append({
                    "step": 4,
                    "title": "Contact the app developer",
                    "description": f"Let the '{primary['app_name']}' team know about the issue. They may already be working on a fix or can help you troubleshoot.",
                    "why": "App developers want to know about bugs - your report helps everyone!"
                })
            else:
                # Single app guidance (no known conflict, new install)
                actions.append({
                    "step": 1,
                    "title": f"Disable '{primary['app_name']}' temporarily",
                    "description": f"Go to your Shopify admin → Apps, find '{primary['app_name']}', and disable it. This won't delete anything, just turns it off.",
                    "why": f"This app is {primary['confidence_label'].lower()} causing the issue based on when it was installed."
                })
                actions.append({
                    "step": 2,
                    "title": "Check if the problem is fixed",
                    "description": "Open your store in a new browser window (or incognito mode) and check if things are back to normal.",
                    "why": "This confirms whether that app was the cause."
                })
                actions.append({
                    "step": 3,
                    "title": "If it's NOT fixed, re-enable and try the next suspect",
                    "description": "Turn the app back on, then disable the next most likely app. Repeat until you find the culprit.",
                    "why": "Sometimes our best guess isn't right - systematic testing will find the real cause."
                })
                actions.append({
                    "step": 4,
                    "title": "Decide what to do next",
                    "description": f"If disabling '{primary['app_name']}' fixed the issue, you can: keep it disabled, contact the app developer for help, or look for an alternative app.",
                    "why": "You have options - don't feel stuck!"
                })
        elif suspects:
            # Lower confidence - suggest testing multiple
            actions.append({
                "step": 1,
                "title": "Test your recently installed apps one by one",
                "description": "Disable each recent app one at a time, checking your store after each to find the culprit.",
                "why": "We found a few possible causes, so testing each one will pinpoint the exact issue."
            })
            suspect_names = [s["app_name"] for s in suspects[:3]]
            actions.append({
                "step": 2,
                "title": f"Start with: {', '.join(suspect_names)}",
                "description": "These apps were installed around the time issues started appearing.",
                "why": "Testing in order of likelihood saves you time."
            })
            actions.append({
                "step": 3,
                "title": "If none of those fix it",
                "description": "The issue might be from a theme update or a change you made manually. Check your theme's recent changes in Shopify admin → Online Store → Themes → Actions → Edit code → Older versions.",
                "why": "Not all issues come from apps - theme updates can also cause problems."
            })
        else:
            # No suspects - general guidance
            actions.append({
                "step": 1,
                "title": "Review your recently installed apps",
                "description": "Check which apps you've added in the last 2 weeks. Try disabling them one at a time.",
                "why": "Most theme issues are caused by app conflicts."
            })
            actions.append({
                "step": 2,
                "title": "Check your theme customizations",
                "description": "If you recently edited your theme code directly, those changes might be causing issues.",
                "why": "Manual code changes can sometimes conflict with apps."
            })
            actions.append({
                "step": 3,
                "title": "If nothing works",
                "description": "Try reverting your theme to a previous version: Shopify admin → Online Store → Themes → Actions → Edit code → Older versions.",
                "why": "This can undo recent changes that may have caused the issue."
            })
        
        # Always add this final action
        actions.append({
            "step": len(actions) + 1,
            "title": "Still stuck? We're here to help",
            "description": "Run another scan to get fresh data, or contact the app developer directly. You can also reach out to a Shopify Expert if the issue persists.",
            "why": "Sometimes issues need expert eyes. Don't struggle alone!"
        })
        
        return actions


# Factory function
def get_issue_correlation_service(db: AsyncSession) -> IssueCorrelationService:
    return IssueCorrelationService(db)