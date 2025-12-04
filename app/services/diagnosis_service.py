"""
Sherlock - Diagnosis Service
Orchestrates all diagnostic scans and generates actionable recommendations
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.db.models import Store, Diagnosis, InstalledApp, ThemeIssue, PerformanceSnapshot
from app.services.app_scanner_service import AppScannerService
from app.services.theme_analyzer_service import ThemeAnalyzerService
from app.services.performance_service import PerformanceService
from app.services.conflict_database import ConflictDatabase
from app.services.orphan_code_service import OrphanCodeService
from app.services.timeline_service import TimelineService
from app.services.community_reports_service import CommunityReportsService
from app.services.reddit_service import reddit_service


class DiagnosisService:
    """
    Main diagnostic service that orchestrates all scans
    and generates comprehensive reports with recommendations
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.app_scanner = AppScannerService(db)
        self.theme_analyzer = ThemeAnalyzerService(db)
        self.performance_service = PerformanceService(db)
        # New enhanced services
        self.conflict_db = ConflictDatabase()
        self.orphan_service = OrphanCodeService(db)
        self.timeline_service = TimelineService(db)
        self.community_service = CommunityReportsService(db)
    
    async def run_diagnosis(
        self, 
        store: Store, 
        diagnosis_id: str,
        scan_type: str = "full"
    ) -> Dict[str, Any]:
        """
        Run a diagnostic scan based on type:
        - full: Complete scan (apps + theme + performance)
        - quick: Fast check of recently installed apps only
        - apps_only: Scan installed apps and their risk factors
        - theme_only: Analyze theme code for conflicts
        - performance: Performance metrics and slow resources
        """
        print(f"🔍 [Diagnosis] Starting {scan_type} scan for {store.shopify_domain}")
        
        # Update diagnosis status to running
        await self._update_diagnosis_status(diagnosis_id, "running")
        
        results = {
            "scan_type": scan_type,
            "store": store.shopify_domain,
            "started_at": datetime.utcnow().isoformat(),
        }
        
        try:
            if scan_type == "full":
                results = await self._run_full_scan(store, results)
            elif scan_type == "quick":
                results = await self._run_quick_scan(store, results)
            elif scan_type == "apps_only":
                results = await self._run_apps_scan(store, results)
            elif scan_type == "theme_only":
                results = await self._run_theme_scan(store, results)
            elif scan_type == "performance":
                results = await self._run_performance_scan(store, results)
            else:
                results["error"] = f"Unknown scan type: {scan_type}"
            
            # Generate recommendations
            if "error" not in results:
                results["recommendations"] = await self._generate_recommendations(results)
                results["summary"] = self._generate_summary(results)
            
            # Update diagnosis record
            await self._save_diagnosis_results(diagnosis_id, results)
            
            print(f"✅ [Diagnosis] Scan complete for {store.shopify_domain}")
            
        except Exception as e:
            print(f"❌ [Diagnosis] Scan failed: {e}")
            results["error"] = str(e)
            await self._update_diagnosis_status(diagnosis_id, "failed")
        
        return results
    
    async def _run_full_scan(self, store: Store, results: Dict) -> Dict[str, Any]:
        """Run complete diagnostic scan with all enhanced features"""
        # 1. Scan apps
        app_results = await self.app_scanner.scan_store_apps(store)
        results["apps"] = app_results
        
        # 2. Analyze theme
        theme_results = await self.theme_analyzer.analyze_theme(store)
        results["theme"] = theme_results
        
        # 3. Measure performance
        performance_results = await self.performance_service.run_full_performance_audit(store)
        results["performance"] = performance_results
        
        # ===== NEW ENHANCED ANALYSES =====
        
        # 5. Check for known app conflicts
        installed_app_names = [app["app_name"] for app in app_results.get("apps", [])]
        conflicts = self.conflict_db.check_conflicts(installed_app_names)
        results["known_conflicts"] = conflicts
        
        # 6. Check for duplicate functionality
        duplicates = self.conflict_db.get_duplicate_functionality_apps(installed_app_names)
        results["duplicate_functionality"] = duplicates
        
        # 7. Scan for orphan code from uninstalled apps
        orphan_results = await self.orphan_service.scan_for_orphan_code(store)
        results["orphan_code"] = orphan_results
        
        # 8. Build timeline and find correlations with installs
        timeline_data = await self.timeline_service.build_store_timeline(store)
        results["timeline_correlations"] = timeline_data.get("correlations", [])
        
        # 9. Get community insights for installed apps
        community_insights = self.community_service.generate_community_insights(installed_app_names)
        results["community_insights"] = community_insights
        
        # 10. Get suggested removal order
        removal_suggestions = await self.timeline_service.suggest_removal_order(store)
        results["suggested_removal_order"] = removal_suggestions
        
        # 11. NEW: Fetch live Reddit data for installed apps
        reddit_insights = await self._fetch_reddit_insights(installed_app_names)
        results["reddit_insights"] = reddit_insights
        
        # 4. Cross-reference findings (including Reddit data)
        results["correlations"] = await self._find_correlations(
            app_results, theme_results, performance_results, reddit_insights
        )
        
        # Calculate totals (enhanced)
        results["total_issues"] = (
            app_results.get("suspect_count", 0) +
            theme_results.get("total_issues", 0) +
            len(performance_results.get("blocking_scripts", [])) +
            len(conflicts) +
            orphan_results.get("total_orphan_instances", 0)
        )
        
        return results
    
    async def _run_quick_scan(self, store: Store, results: Dict) -> Dict[str, Any]:
        """Quick scan - check recently installed apps only"""
        # Get apps installed in last 7 days
        recent_apps = await self.app_scanner.get_recently_installed_apps(store, days=7)
        
        suspects = []
        for app in recent_apps:
            risk_data = await self.app_scanner.calculate_risk_score(
                app.app_name, app.installed_on
            )
            if risk_data["is_suspect"]:
                suspects.append({
                    "app_name": app.app_name,
                    "installed_on": app.installed_on.isoformat() if app.installed_on else None,
                    "risk_score": risk_data["risk_score"],
                    "risk_reasons": risk_data["risk_reasons"]
                })
        
        results["recent_apps_count"] = len(recent_apps)
        results["suspects"] = suspects
        results["total_issues"] = len(suspects)
        
        if suspects:
            results["likely_culprit"] = suspects[0]  # Highest risk
            results["quick_verdict"] = f"Found {len(suspects)} suspect app(s). Most likely culprit: {suspects[0]['app_name']}"
        else:
            results["quick_verdict"] = "No recently installed apps appear suspicious. Consider running a full scan."
        
        return results
    
    async def _run_apps_scan(self, store: Store, results: Dict) -> Dict[str, Any]:
        """Scan installed apps only"""
        app_results = await self.app_scanner.scan_store_apps(store)
        results["apps"] = app_results
        results["total_issues"] = app_results.get("suspect_count", 0)
        return results
    
    async def _run_theme_scan(self, store: Store, results: Dict) -> Dict[str, Any]:
        """Scan theme code only"""
        theme_results = await self.theme_analyzer.analyze_theme(store)
        results["theme"] = theme_results
        results["total_issues"] = theme_results.get("total_issues", 0)
        return results
    
    async def _run_performance_scan(self, store: Store, results: Dict) -> Dict[str, Any]:
        """Run performance audit only"""
        performance_results = await self.performance_service.run_full_performance_audit(store)
        results["performance"] = performance_results
        results["total_issues"] = len(performance_results.get("recommendations", []))
        return results
    
    async def _fetch_reddit_insights(self, app_names: List[str]) -> Dict[str, Any]:
        """
        Fetch live Reddit data for installed apps
        Returns reputation scores and community feedback
        """
        print(f"🔍 [Reddit] Fetching insights for {len(app_names)} apps...")
        
        app_insights = []
        high_risk_apps = []
        total_reddit_issues = 0
        
        for app_name in app_names[:10]:  # Limit to 10 apps to avoid rate limiting
            try:
                reputation = await reddit_service.check_app_reputation(app_name)
                
                app_insight = {
                    "app_name": app_name,
                    "reddit_risk_score": reputation.get("reddit_risk_score", 0),
                    "posts_found": reputation.get("posts_found", 0),
                    "sentiment": reputation.get("sentiment", "unknown"),
                    "severity": reputation.get("severity", "low"),
                    "common_issues": reputation.get("common_issues", []),
                    "recommendation": reputation.get("recommendation", ""),
                    "sample_posts": reputation.get("sample_posts", [])[:3],
                }
                
                app_insights.append(app_insight)
                
                # Track high-risk apps
                if reputation.get("reddit_risk_score", 0) >= 50:
                    high_risk_apps.append({
                        "app_name": app_name,
                        "risk_score": reputation.get("reddit_risk_score", 0),
                        "sentiment": reputation.get("sentiment", "unknown"),
                        "posts_found": reputation.get("posts_found", 0),
                        "top_issues": [i["issue"] for i in reputation.get("common_issues", [])[:3]]
                    })
                
                # Count issues mentioned
                total_reddit_issues += len(reputation.get("common_issues", []))
                
            except Exception as e:
                print(f"⚠️ [Reddit] Error fetching data for {app_name}: {e}")
                continue
        
        # Sort by risk score
        app_insights.sort(key=lambda x: x["reddit_risk_score"], reverse=True)
        high_risk_apps.sort(key=lambda x: x["risk_score"], reverse=True)
        
        print(f"✅ [Reddit] Found {len(high_risk_apps)} high-risk apps from Reddit data")
        
        return {
            "apps_analyzed": len(app_insights),
            "app_insights": app_insights,
            "high_risk_apps": high_risk_apps,
            "total_reddit_issues": total_reddit_issues,
            "summary": self._generate_reddit_summary(high_risk_apps)
        }
    
    def _generate_reddit_summary(self, high_risk_apps: List[Dict]) -> str:
        """Generate a summary of Reddit findings"""
        if not high_risk_apps:
            return "No significant issues found in Reddit community discussions."
        
        if len(high_risk_apps) == 1:
            app = high_risk_apps[0]
            return f"⚠️ Reddit users frequently report issues with {app['app_name']} (Risk: {app['risk_score']}/100)"
        
        app_names = [a["app_name"] for a in high_risk_apps[:3]]
        return f"⚠️ Reddit users report issues with: {', '.join(app_names)}. Review these apps carefully."
    
    async def _find_correlations(
        self,
        app_results: Dict,
        theme_results: Dict,
        performance_results: Dict,
        reddit_insights: Dict = None
    ) -> List[Dict[str, Any]]:
        """
        Cross-reference findings to identify patterns:
        - Apps detected in both app list AND theme code
        - Apps that appear in blocking scripts
        - Apps with negative Reddit sentiment
        - Multiple signals pointing to same culprit
        """
        correlations = []
        
        # Get suspect app names
        suspect_apps = set(app_results.get("suspects", []))
        
        # Get apps detected in theme
        theme_apps = set(theme_results.get("apps_detected", []))
        
        # Get apps from blocking scripts
        blocking_apps = set()
        for script in performance_results.get("blocking_scripts", []):
            domain = script.get("domain", "").lower()
            # Extract app name from domain
            for app in suspect_apps | theme_apps:
                if app.lower() in domain:
                    blocking_apps.add(app)
        
        # NEW: Get high-risk apps from Reddit
        reddit_risk_apps = {}
        if reddit_insights:
            for app_data in reddit_insights.get("high_risk_apps", []):
                reddit_risk_apps[app_data["app_name"]] = app_data
        
        # Find apps that appear in multiple places
        all_apps = suspect_apps | theme_apps | blocking_apps | set(reddit_risk_apps.keys())
        
        for app in all_apps:
            signals = []
            confidence = 0
            reddit_data = None
            
            if app in suspect_apps:
                signals.append("Flagged as high-risk app")
                confidence += 25
            
            if app in theme_apps:
                signals.append("Detected injecting code into theme")
                confidence += 30
            
            if app in blocking_apps:
                signals.append("Identified as blocking/slow script")
                confidence += 30
            
            # NEW: Reddit signals
            if app in reddit_risk_apps:
                reddit_info = reddit_risk_apps[app]
                reddit_score = reddit_info.get("risk_score", 0)
                posts_found = reddit_info.get("posts_found", 0)
                sentiment = reddit_info.get("sentiment", "unknown")
                
                if reddit_score >= 70:
                    signals.append(f"HIGH Reddit risk ({reddit_score}/100) - {posts_found} complaints found")
                    confidence += 35
                elif reddit_score >= 50:
                    signals.append(f"Moderate Reddit risk ({reddit_score}/100) - {posts_found} posts found")
                    confidence += 20
                
                if sentiment == "negative":
                    signals.append("Negative sentiment in Reddit community")
                    confidence += 15
                
                reddit_data = {
                    "risk_score": reddit_score,
                    "posts_found": posts_found,
                    "sentiment": sentiment,
                    "top_issues": reddit_info.get("top_issues", [])
                }
            
            if len(signals) >= 1:  # Include apps with at least 1 signal
                correlations.append({
                    "app_name": app,
                    "signals": signals,
                    "confidence": min(confidence, 100),
                    "verdict": "HIGHLY LIKELY CULPRIT" if confidence >= 70 else "POSSIBLE CULPRIT" if confidence >= 40 else "LOW RISK",
                    "reddit_data": reddit_data
                })
        
        # Sort by confidence
        correlations.sort(key=lambda x: x["confidence"], reverse=True)
        
        return correlations
    
    async def _generate_recommendations(self, results: Dict) -> List[Dict[str, Any]]:
        """Generate prioritized, actionable recommendations including enhanced analyses"""
        recommendations = []
        
        # High-confidence correlations get top priority
        correlations = results.get("correlations", [])
        for corr in correlations[:3]:  # Top 3
            if corr["confidence"] >= 70:
                recommendations.append({
                    "priority": 1,
                    "type": "uninstall_test",
                    "app_name": corr["app_name"],
                    "confidence": corr["confidence"],
                    "action": f"Try uninstalling '{corr['app_name']}' to test if it resolves your issue",
                    "reason": " + ".join(corr["signals"]),
                    "reversible": True
                })
        
        # ===== NEW: Suggested removal order from timeline analysis =====
        removal_suggestions = results.get("suggested_removal_order", [])
        for suggestion in removal_suggestions[:3]:
            if suggestion["app_name"] not in [r.get("app_name") for r in recommendations]:
                recommendations.append({
                    "priority": 1,
                    "type": "timeline_based_removal",
                    "app_name": suggestion["app_name"],
                    "action": f"Uninstall '{suggestion['app_name']}' - {suggestion['reason']}",
                    "reason": suggestion["reason"],
                    "confidence": suggestion["confidence"],
                    "reversible": True
                })
        
        # ===== NEW: Known app conflicts =====
        conflicts = results.get("known_conflicts", [])
        for conflict in conflicts:
            recommendations.append({
                "priority": 1 if conflict["severity"] == "critical" else 2,
                "type": "resolve_conflict",
                "action": f"CONFLICT: {' vs '.join(conflict['conflicting_apps'])}",
                "reason": conflict["description"],
                "solution": conflict["solution"],
                "community_reports": conflict.get("community_reports", 0),
            })
        
        # ===== NEW: Duplicate functionality =====
        duplicates = results.get("duplicate_functionality", {})
        for category, apps in duplicates.items():
            recommendations.append({
                "priority": 2,
                "type": "remove_duplicate",
                "action": f"Remove duplicate {category.replace('_', ' ')} apps: {', '.join(apps)}",
                "reason": f"Having multiple {category.replace('_', ' ')} apps causes conflicts and slows your store",
                "solution": f"Keep only one {category.replace('_', ' ')} app",
            })
        
        # ===== NEW: Orphan code cleanup =====
        orphan_data = results.get("orphan_code", {})
        if orphan_data.get("total_orphan_instances", 0) > 0:
            for orphan_rec in orphan_data.get("recommendations", [])[:2]:
                recommendations.append({
                    "priority": orphan_rec.get("priority", 2),
                    "type": "cleanup_orphan_code",
                    "action": orphan_rec["action"],
                    "reason": orphan_rec["reason"],
                    "how_to_fix": orphan_rec.get("how_to_fix", ""),
                    "files_to_check": orphan_rec.get("files_to_check", []),
                })
        
        # ===== NEW: Timeline correlations (performance impact) =====
        timeline_corrs = results.get("timeline_correlations", [])
        for tc in timeline_corrs[:2]:
            if tc.get("impact") == "negative" and tc.get("confidence", 0) >= 60:
                recommendations.append({
                    "priority": 1,
                    "type": "performance_correlation",
                    "app_name": tc["app_name"],
                    "action": f"'{tc['app_name']}' degraded performance after install",
                    "reason": tc["verdict"],
                    "changes": tc.get("changes", {}),
                })
        
        # Add app-specific recommendations
        apps = results.get("apps", {})
        for app_data in apps.get("apps", [])[:5]:  # Top 5 risky apps
            if app_data.get("is_suspect") and app_data["app_name"] not in [
                r.get("app_name") for r in recommendations
            ]:
                recommendations.append({
                    "priority": 2,
                    "type": "review_app",
                    "app_name": app_data["app_name"],
                    "confidence": app_data.get("risk_score", 0),
                    "action": f"Review '{app_data['app_name']}' - {app_data.get('risk_reasons', ['Unknown risk'])[0]}",
                    "reason": ", ".join(app_data.get("risk_reasons", [])),
                    "reversible": True
                })
        
        # Add theme-specific recommendations
        theme = results.get("theme", {})
        if theme.get("by_severity", {}).get("critical", 0) > 0:
            recommendations.append({
                "priority": 1,
                "type": "fix_theme",
                "action": "Critical theme issues detected - review theme code immediately",
                "reason": f"{theme['by_severity']['critical']} critical issue(s) in theme code",
                "reversible": False
            })
        
        # Add performance recommendations
        performance = results.get("performance", {})
        if performance.get("average_score", 100) < 50:
            recommendations.append({
                "priority": 1,
                "type": "performance",
                "action": "Store performance is poor - consider removing heavy apps",
                "reason": f"Performance score: {performance.get('average_score', 0):.0f}/100",
                "details": performance.get("recommendations", [])
            })
        
        # ===== NEW: Community insights recommendations =====
        community = results.get("community_insights", {})
        for comm_rec in community.get("recommendations", [])[:3]:
            if comm_rec["type"] not in [r.get("type") for r in recommendations]:
                recommendations.append({
                    "priority": comm_rec.get("priority", 3),
                    "type": comm_rec["type"],
                    "action": comm_rec["action"],
                    "reason": comm_rec.get("reason", ""),
                    "solution": comm_rec.get("solution", ""),
                })
        
        # ===== NEW: Reddit-based recommendations =====
        reddit_insights = results.get("reddit_insights", {})
        for app_insight in reddit_insights.get("high_risk_apps", [])[:3]:
            app_name = app_insight.get("app_name")
            if app_name not in [r.get("app_name") for r in recommendations]:
                risk_score = app_insight.get("risk_score", 0)
                sentiment = app_insight.get("sentiment", "unknown")
                posts_found = app_insight.get("posts_found", 0)
                top_issues = app_insight.get("top_issues", [])
                
                recommendations.append({
                    "priority": 1 if risk_score >= 70 else 2,
                    "type": "reddit_warning",
                    "app_name": app_name,
                    "action": f"⚠️ Review '{app_name}' - Reddit users report issues",
                    "reason": f"Reddit risk score: {risk_score}/100, {posts_found} posts found, sentiment: {sentiment}",
                    "common_issues": top_issues,
                    "source": "Reddit r/shopify community",
                    "confidence": risk_score,
                    "reversible": True
                })
        
        # Sort by priority
        recommendations.sort(key=lambda x: x["priority"])
        
        # Deduplicate by app_name (keep highest priority)
        seen_apps = set()
        deduped = []
        for rec in recommendations:
            app_name = rec.get("app_name")
            if app_name and app_name in seen_apps:
                continue
            if app_name:
                seen_apps.add(app_name)
            deduped.append(rec)
        recommendations = deduped
        
        # Add step-by-step troubleshooting guide
        recommendations.append({
            "priority": 99,
            "type": "guide",
            "action": "Step-by-step troubleshooting process",
            "steps": [
                "1. Note down the exact issue you're experiencing",
                "2. Uninstall the #1 suspect app identified above",
                "3. Clear your browser cache and test your store",
                "4. If issue persists, reinstall the app and try the next suspect",
                "5. Once you find the culprit, contact that app's support for help",
                "6. Check for orphan code from previously uninstalled apps",
                "7. Review the timeline to see when issues started"
            ]
        })
        
        return recommendations
    
    def _generate_summary(self, results: Dict) -> Dict[str, Any]:
        """Generate a human-readable summary of findings"""
        summary = {
            "verdict": "unknown",
            "confidence": 0,
            "primary_suspect": None,
            "total_issues": results.get("total_issues", 0),
            "quick_summary": "",
            "reddit_summary": None
        }
        
        correlations = results.get("correlations", [])
        
        # Include Reddit insights in summary
        reddit_insights = results.get("reddit_insights", {})
        if reddit_insights.get("high_risk_apps"):
            top_reddit = reddit_insights["high_risk_apps"][0]
            summary["reddit_summary"] = (
                f"📢 Reddit community reports issues with {top_reddit['app_name']} "
                f"(Risk: {top_reddit['risk_score']}/100, {top_reddit['posts_found']} posts)"
            )
        
        if correlations and correlations[0]["confidence"] >= 70:
            top = correlations[0]
            summary["verdict"] = "culprit_identified"
            summary["confidence"] = top["confidence"]
            summary["primary_suspect"] = top["app_name"]
            
            # Add Reddit context if available
            reddit_note = ""
            if top.get("reddit_data"):
                reddit_note = f" Reddit confirms issues ({top['reddit_data']['posts_found']} posts)."
            
            summary["quick_summary"] = (
                f"🎯 Primary suspect: {top['app_name']} "
                f"(Confidence: {top['confidence']}%).{reddit_note} "
                f"Recommendation: Try uninstalling this app first."
            )
        elif correlations:
            summary["verdict"] = "suspects_found"
            summary["confidence"] = correlations[0]["confidence"]
            summary["primary_suspect"] = correlations[0]["app_name"]
            summary["quick_summary"] = (
                f"🔍 Found {len(correlations)} possible suspect(s). "
                f"Most likely: {correlations[0]['app_name']}. "
                f"Try the troubleshooting steps to narrow it down."
            )
        elif results.get("total_issues", 0) > 0:
            summary["verdict"] = "issues_found"
            summary["quick_summary"] = (
                f"⚠️ Found {results['total_issues']} potential issue(s), "
                f"but couldn't pinpoint a specific app. "
                f"Review the detailed findings below."
            )
        else:
            summary["verdict"] = "no_issues"
            summary["quick_summary"] = (
                "✅ No obvious issues detected. If you're still experiencing problems, "
                "try describing the specific issue for a more targeted diagnosis."
            )
        
        return summary
    
    async def _update_diagnosis_status(self, diagnosis_id: str, status: str):
        """Update diagnosis status"""
        await self.db.execute(
            update(Diagnosis)
            .where(Diagnosis.id == diagnosis_id)
            .values(status=status)
        )
        await self.db.flush()
    
    async def _save_diagnosis_results(self, diagnosis_id: str, results: Dict):
        """Save diagnosis results to database"""
        result = await self.db.execute(
            select(Diagnosis).where(Diagnosis.id == diagnosis_id)
        )
        diagnosis = result.scalar_one_or_none()
        
        if diagnosis:
            diagnosis.status = "completed"
            diagnosis.completed_at = datetime.utcnow()
            diagnosis.total_apps_scanned = results.get("apps", {}).get("total_apps", 0)
            diagnosis.issues_found = results.get("total_issues", 0)
            diagnosis.suspect_apps = results.get("apps", {}).get("suspects", [])
            diagnosis.performance_score = results.get("performance", {}).get("average_score")
            diagnosis.results = results
            diagnosis.recommendations = results.get("recommendations", [])
            
            await self.db.flush()
    
    async def get_diagnosis_report(self, diagnosis_id: str) -> Optional[Dict[str, Any]]:
        """Get formatted diagnosis report"""
        result = await self.db.execute(
            select(Diagnosis).where(Diagnosis.id == diagnosis_id)
        )
        diagnosis = result.scalar_one_or_none()
        
        if not diagnosis:
            return None
        
        return {
            "diagnosis_id": diagnosis.id,
            "status": diagnosis.status,
            "scan_type": diagnosis.scan_type,
            "started_at": diagnosis.started_at.isoformat() if diagnosis.started_at else None,
            "completed_at": diagnosis.completed_at.isoformat() if diagnosis.completed_at else None,
            "summary": diagnosis.results.get("summary") if diagnosis.results else None,
            "total_apps_scanned": diagnosis.total_apps_scanned,
            "issues_found": diagnosis.issues_found,
            "suspect_apps": diagnosis.suspect_apps,
            "performance_score": diagnosis.performance_score,
            "recommendations": diagnosis.recommendations,
            "full_results": diagnosis.results
        }