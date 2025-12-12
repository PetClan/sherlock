"""
Sherlock - Issue Correlation Service
Matches detected issues to likely app culprits based on timing
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_

from app.db.models import Store, InstalledApp, ThemeIssue, DailyScan


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
            select(Store).where(Store.shop_domain == shop_domain)
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
        
        # Correlate issues with apps
        correlations = self._correlate_issues_to_apps(issues, recent_apps, last_clean_scan)
        
        # Build merchant-friendly diagnosis
        diagnosis = self._build_diagnosis(issues, correlations, recent_apps)
        
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
    
    async def _get_recent_apps(self, store_id: str, days: int = 14) -> List[InstalledApp]:
        """Get apps installed in the last N days"""
        since = datetime.utcnow() - timedelta(days=days)
        result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store_id)
            .where(InstalledApp.installed_on >= since)
            .order_by(desc(InstalledApp.installed_on))
        )
        return result.scalars().all()
    
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
                        "installed_on": None
                    }
                correlations[app_name]["issues_caused"].append({
                    "type": issue.issue_type,
                    "file": issue.file_path,
                    "severity": issue.severity
                })
                continue
            
            # Otherwise, look for apps installed before issue was detected
            for app in apps:
                if not app.installed_on:
                    continue
                
                # App was installed before issue appeared
                if app.installed_on <= issue_date:
                    # Calculate time gap
                    gap = (issue_date - app.installed_on).days
                    
                    # Closer in time = higher confidence
                    if gap <= 1:
                        confidence = 85
                        reasoning = f"Installed 1 day before issue appeared"
                    elif gap <= 3:
                        confidence = 70
                        reasoning = f"Installed {gap} days before issue appeared"
                    elif gap <= 7:
                        confidence = 50
                        reasoning = f"Installed {gap} days before issue appeared"
                    else:
                        confidence = 30
                        reasoning = f"Installed {gap} days ago"
                    
                    # Boost confidence if app is flagged as suspect
                    if app.is_suspect:
                        confidence = min(95, confidence + 15)
                        reasoning += " (flagged as potentially problematic)"
                    
                    app_name = app.app_name
                    if app_name not in correlations:
                        correlations[app_name] = {
                            "confidence": confidence,
                            "issues_caused": [],
                            "reasoning": reasoning,
                            "installed_on": app.installed_on.isoformat() if app.installed_on else None
                        }
                    else:
                        # Update confidence if this correlation is stronger
                        if confidence > correlations[app_name]["confidence"]:
                            correlations[app_name]["confidence"] = confidence
                            correlations[app_name]["reasoning"] = reasoning
                    
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
        recent_apps: List[InstalledApp]
    ) -> Dict[str, Any]:
        """Build merchant-friendly diagnosis with clear actions"""
        
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
            suspects.append({
                "app_name": app_name,
                "confidence": data["confidence"],
                "confidence_label": self._get_confidence_label(data["confidence"]),
                "reasoning": data["reasoning"],
                "issues_caused": len(data["issues_caused"]),
                "installed_on": data["installed_on"]
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
                "message": self._get_suspect_message(top)
            }
        
        # Build recommended actions
        actions = self._build_actions(primary_suspect, suspects, issues)
        
        return {
            "issues": formatted_issues,
            "primary_suspect": primary_suspect,
            "all_suspects": suspects,
            "actions": actions
        }
    
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
        issues: List[ThemeIssue]
    ) -> List[Dict]:
        """Build step-by-step actions for the merchant"""
        actions = []
        
        if primary and primary["confidence"] >= 60:
            # High confidence - give direct action
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
                "title": "Decide what to do next",
                "description": f"If disabling '{primary['app_name']}' fixed the issue, you can either keep it disabled, contact the app developer for help, or look for an alternative app.",
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
        
        # Always add this final action
        actions.append({
            "step": len(actions) + 1,
            "title": "Still stuck? Run another scan",
            "description": "Click 'Run Full Scan' to get fresh data. If issues persist, consider reaching out to a Shopify expert.",
            "why": "Sometimes issues resolve themselves after app updates."
        })
        
        return actions


# Factory function
def get_issue_correlation_service(db: AsyncSession) -> IssueCorrelationService:
    return IssueCorrelationService(db)