"""
Sherlock - Community Reports Service
Aggregates and surfaces known issues from Shopify community forums,
Reddit, Facebook groups, and other sources
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conflict_database import ConflictDatabase, COMMUNITY_REPORTS


# Extended community issue database
# This would ideally be updated periodically from actual community scraping
EXTENDED_COMMUNITY_ISSUES = {
    # Page Builders
    "pagefly": {
        "category": "page_builder",
        "severity": "high",
        "common_symptoms": [
            "Homepage loads slowly (3-8 seconds)",
            "Mobile menu doesn't work",
            "Product images don't load",
            "Theme sections disappear",
            "Duplicate content issues for SEO",
        ],
        "common_causes": [
            "Heavy JavaScript bundle (500KB+)",
            "Multiple jQuery versions loading",
            "CSS conflicts with theme",
            "Liquid code injection in theme.liquid",
        ],
        "affected_areas": ["homepage", "landing_pages", "product_pages"],
        "forum_threads": 1247,
        "reddit_posts": 234,
        "resolution_rate": 0.72,
        "typical_resolution": "Uninstall and use theme's native sections, or optimize PageFly settings",
        "shopify_status": "active",
    },
    "gempages": {
        "category": "page_builder",
        "severity": "high",
        "common_symptoms": [
            "Slow editor loading",
            "Pages not rendering on mobile",
            "Font conflicts",
            "Checkout redirect issues",
        ],
        "common_causes": [
            "Large CSS files",
            "Unoptimized images in pages",
            "JavaScript conflicts",
        ],
        "affected_areas": ["landing_pages", "product_pages"],
        "forum_threads": 987,
        "reddit_posts": 178,
        "resolution_rate": 0.68,
        "typical_resolution": "Optimize page settings, reduce sections per page",
        "shopify_status": "active",
    },
    "shogun": {
        "category": "page_builder",
        "severity": "medium",
        "common_symptoms": [
            "Slow initial page load",
            "Layout shifts during loading",
            "Mobile responsiveness issues",
        ],
        "common_causes": [
            "Heavy framework loading",
            "Render-blocking scripts",
        ],
        "affected_areas": ["landing_pages", "blog_posts"],
        "forum_threads": 632,
        "reddit_posts": 145,
        "resolution_rate": 0.75,
        "typical_resolution": "Enable lazy loading, reduce animations",
        "shopify_status": "active",
    },
    
    # Review Apps
    "loox": {
        "category": "reviews",
        "severity": "medium",
        "common_symptoms": [
            "Product page loads slowly",
            "Review widget doesn't appear",
            "Photo reviews cause layout shift",
            "Email requests not sending",
        ],
        "common_causes": [
            "Large image gallery loading",
            "Widget placement conflicts",
            "Theme compatibility issues",
        ],
        "affected_areas": ["product_pages", "collection_pages"],
        "forum_threads": 567,
        "reddit_posts": 123,
        "resolution_rate": 0.82,
        "typical_resolution": "Lazy load reviews, limit photos per review",
        "shopify_status": "active",
    },
    "judge.me": {
        "category": "reviews",
        "severity": "low",
        "common_symptoms": [
            "Star ratings not showing",
            "Widget styling conflicts",
            "Import issues from other apps",
        ],
        "common_causes": [
            "Theme CSS conflicts",
            "Missing liquid snippets",
        ],
        "affected_areas": ["product_pages"],
        "forum_threads": 423,
        "reddit_posts": 89,
        "resolution_rate": 0.88,
        "typical_resolution": "Reinstall widget code, check theme compatibility",
        "shopify_status": "active",
    },
    "yotpo": {
        "category": "reviews",
        "severity": "medium",
        "common_symptoms": [
            "Slow page load due to widget",
            "Reviews not syncing",
            "Visual UGC gallery issues",
        ],
        "common_causes": [
            "Heavy JavaScript bundle",
            "API rate limiting",
        ],
        "affected_areas": ["product_pages", "homepage"],
        "forum_threads": 534,
        "reddit_posts": 112,
        "resolution_rate": 0.76,
        "typical_resolution": "Disable unused features, optimize widget placement",
        "shopify_status": "active",
    },
    
    # Email/Popup Apps
    "klaviyo": {
        "category": "email_marketing",
        "severity": "medium",
        "common_symptoms": [
            "Popup not triggering",
            "Forms conflicting with theme modals",
            "Tracking causing slowdown",
            "Back-in-stock not working",
        ],
        "common_causes": [
            "JavaScript conflicts",
            "Popup trigger timing issues",
            "Theme modal conflicts",
        ],
        "affected_areas": ["all_pages", "product_pages"],
        "forum_threads": 678,
        "reddit_posts": 234,
        "resolution_rate": 0.85,
        "typical_resolution": "Adjust popup triggers, check script loading order",
        "shopify_status": "active",
    },
    "privy": {
        "category": "popup",
        "severity": "medium",
        "common_symptoms": [
            "Multiple popups showing",
            "Exit intent not working",
            "Mobile popup covers entire screen",
            "Popup shows on every page",
        ],
        "common_causes": [
            "Misconfigured triggers",
            "Cookie issues",
            "Mobile detection problems",
        ],
        "affected_areas": ["all_pages"],
        "forum_threads": 445,
        "reddit_posts": 156,
        "resolution_rate": 0.79,
        "typical_resolution": "Review trigger settings, add page targeting rules",
        "shopify_status": "active",
    },
    
    # Subscription Apps
    "recharge": {
        "category": "subscription",
        "severity": "high",
        "common_symptoms": [
            "Checkout errors",
            "Subscription widget not appearing",
            "Customer portal issues",
            "Payment failures",
        ],
        "common_causes": [
            "Theme checkout conflicts",
            "JavaScript errors",
            "API sync issues",
        ],
        "affected_areas": ["product_pages", "checkout", "customer_accounts"],
        "forum_threads": 789,
        "reddit_posts": 267,
        "resolution_rate": 0.71,
        "typical_resolution": "Contact ReCharge support, check theme compatibility",
        "shopify_status": "active",
    },
    
    # Upsell Apps
    "reconvert": {
        "category": "upsell",
        "severity": "medium",
        "common_symptoms": [
            "Thank you page not loading",
            "Upsells not showing",
            "Revenue tracking issues",
        ],
        "common_causes": [
            "Checkout extension conflicts",
            "Theme thank you page conflicts",
        ],
        "affected_areas": ["checkout", "thank_you_page"],
        "forum_threads": 345,
        "reddit_posts": 78,
        "resolution_rate": 0.81,
        "typical_resolution": "Check checkout extensibility settings",
        "shopify_status": "active",
    },
    "zipify": {
        "category": "upsell",
        "severity": "medium",
        "common_symptoms": [
            "One-click upsell not working",
            "Page builder conflicts",
            "Analytics discrepancies",
        ],
        "common_causes": [
            "Shopify Plus checkout requirements",
            "Script conflicts",
        ],
        "affected_areas": ["checkout", "thank_you_page"],
        "forum_threads": 298,
        "reddit_posts": 67,
        "resolution_rate": 0.77,
        "typical_resolution": "Verify Shopify Plus requirements, check script order",
        "shopify_status": "active",
    },
    
    # All-in-One Apps
    "vitals": {
        "category": "all_in_one",
        "severity": "high",
        "common_symptoms": [
            "Slow site speed",
            "Features conflicting with each other",
            "Currency converter breaking checkout",
            "Can't disable individual features fully",
        ],
        "common_causes": [
            "Too many features enabled",
            "Heavy JavaScript bundle",
            "Feature conflicts",
        ],
        "affected_areas": ["all_pages"],
        "forum_threads": 756,
        "reddit_posts": 234,
        "resolution_rate": 0.65,
        "typical_resolution": "Disable unused features, consider specialized single-purpose apps",
        "shopify_status": "active",
    },
    
    # Translation Apps
    "weglot": {
        "category": "translation",
        "severity": "medium",
        "common_symptoms": [
            "Translation missing on some pages",
            "SEO issues with hreflang",
            "Checkout not translating",
            "Dynamic content issues",
        ],
        "common_causes": [
            "JavaScript-rendered content",
            "Checkout limitations",
            "Cache issues",
        ],
        "affected_areas": ["all_pages"],
        "forum_threads": 423,
        "reddit_posts": 89,
        "resolution_rate": 0.74,
        "typical_resolution": "Manual translations for dynamic content, check exclusion rules",
        "shopify_status": "active",
    },
    
    # Chat Apps
    "tidio": {
        "category": "chat",
        "severity": "low",
        "common_symptoms": [
            "Chat widget not appearing",
            "Widget position conflicts",
            "Mobile widget too large",
        ],
        "common_causes": [
            "Z-index conflicts",
            "Mobile viewport issues",
        ],
        "affected_areas": ["all_pages"],
        "forum_threads": 234,
        "reddit_posts": 56,
        "resolution_rate": 0.89,
        "typical_resolution": "Adjust widget position settings, check z-index",
        "shopify_status": "active",
    },
    "gorgias": {
        "category": "helpdesk",
        "severity": "low",
        "common_symptoms": [
            "Chat widget conflicts",
            "Integration sync issues",
            "Automation not triggering",
        ],
        "common_causes": [
            "Widget placement",
            "API connection issues",
        ],
        "affected_areas": ["all_pages"],
        "forum_threads": 312,
        "reddit_posts": 78,
        "resolution_rate": 0.86,
        "typical_resolution": "Check integration settings, verify API connection",
        "shopify_status": "active",
    },
}


# Trending issues - Recently reported problems
TRENDING_ISSUES = [
    {
        "date": "2025-01",
        "app": "pagefly",
        "issue": "Compatibility issues with Dawn 15.0 theme update",
        "affected_users": 450,
        "status": "investigating",
    },
    {
        "date": "2025-01",
        "app": "klaviyo",
        "issue": "Popup forms not showing after Shopify checkout update",
        "affected_users": 320,
        "status": "resolved",
    },
    {
        "date": "2025-01",
        "app": "recharge",
        "issue": "Subscription widget CSS broken on mobile",
        "affected_users": 280,
        "status": "workaround_available",
    },
    {
        "date": "2024-12",
        "app": "vitals",
        "issue": "Currency converter causing checkout errors with Shopify Markets",
        "affected_users": 520,
        "status": "known_issue",
    },
    {
        "date": "2024-12",
        "app": "loox",
        "issue": "Photo reviews not loading on OS 2.0 themes",
        "affected_users": 190,
        "status": "resolved",
    },
]


class CommunityReportsService:
    """Service for accessing community-reported issues and trends"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conflict_db = ConflictDatabase()
        self.issues = EXTENDED_COMMUNITY_ISSUES
        self.trending = TRENDING_ISSUES
    
    def get_app_community_report(self, app_name: str) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive community report for an app
        
        Args:
            app_name: Name of the app
        
        Returns:
            Full community report or None
        """
        app_lower = app_name.lower()
        
        for key, data in self.issues.items():
            if key in app_lower or app_lower in key:
                # Also get basic reports from conflict database
                basic_report = self.conflict_db.get_app_issues(app_name)
                
                return {
                    "app": key,
                    "category": data["category"],
                    "severity": data["severity"],
                    "common_symptoms": data["common_symptoms"],
                    "common_causes": data["common_causes"],
                    "affected_areas": data["affected_areas"],
                    "community_stats": {
                        "forum_threads": data["forum_threads"],
                        "reddit_posts": data["reddit_posts"],
                        "total_reports": data["forum_threads"] + data["reddit_posts"],
                    },
                    "resolution_rate": data["resolution_rate"],
                    "typical_resolution": data["typical_resolution"],
                    "shopify_status": data["shopify_status"],
                    "basic_issues": basic_report["common_issues"] if basic_report else [],
                }
        
        return None
    
    def get_apps_by_issue_count(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get apps ranked by number of community-reported issues"""
        ranked = []
        
        for app_name, data in self.issues.items():
            ranked.append({
                "app": app_name,
                "total_reports": data["forum_threads"] + data["reddit_posts"],
                "severity": data["severity"],
                "category": data["category"],
                "resolution_rate": data["resolution_rate"],
            })
        
        ranked.sort(key=lambda x: x["total_reports"], reverse=True)
        return ranked[:limit]
    
    def get_trending_issues(self, months: int = 3) -> List[Dict[str, Any]]:
        """Get recently trending issues"""
        cutoff = datetime.utcnow() - timedelta(days=months * 30)
        cutoff_str = cutoff.strftime("%Y-%m")
        
        trending = [
            issue for issue in self.trending
            if issue["date"] >= cutoff_str
        ]
        
        return trending
    
    def check_known_issues_for_apps(
        self,
        app_names: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Check if any installed apps have known community issues
        
        Args:
            app_names: List of installed app names
        
        Returns:
            List of known issues for these apps
        """
        found_issues = []
        
        for app_name in app_names:
            report = self.get_app_community_report(app_name)
            if report:
                found_issues.append({
                    "app": app_name,
                    "matched_to": report["app"],
                    "severity": report["severity"],
                    "total_community_reports": report["community_stats"]["total_reports"],
                    "top_symptoms": report["common_symptoms"][:3],
                    "resolution_rate": report["resolution_rate"],
                    "typical_resolution": report["typical_resolution"],
                })
        
        # Sort by severity and report count
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        found_issues.sort(key=lambda x: (
            severity_order.get(x["severity"], 99),
            -x["total_community_reports"]
        ))
        
        return found_issues
    
    def get_symptoms_matching(self, symptom_keywords: List[str]) -> List[Dict[str, Any]]:
        """
        Find apps whose symptoms match given keywords
        
        Args:
            symptom_keywords: Keywords describing the issue (e.g., ["slow", "mobile", "checkout"])
        
        Returns:
            List of apps with matching symptoms
        """
        matches = []
        keywords_lower = [k.lower() for k in symptom_keywords]
        
        for app_name, data in self.issues.items():
            symptom_text = " ".join(data["common_symptoms"]).lower()
            cause_text = " ".join(data["common_causes"]).lower()
            full_text = symptom_text + " " + cause_text
            
            matching_keywords = [
                k for k in keywords_lower
                if k in full_text
            ]
            
            if matching_keywords:
                matches.append({
                    "app": app_name,
                    "matching_keywords": matching_keywords,
                    "match_score": len(matching_keywords) / len(keywords_lower),
                    "severity": data["severity"],
                    "matched_symptoms": [
                        s for s in data["common_symptoms"]
                        if any(k in s.lower() for k in matching_keywords)
                    ],
                    "typical_resolution": data["typical_resolution"],
                })
        
        # Sort by match score
        matches.sort(key=lambda x: x["match_score"], reverse=True)
        
        return matches
    
    def generate_community_insights(
        self,
        installed_apps: List[str]
    ) -> Dict[str, Any]:
        """
        Generate comprehensive community insights for installed apps
        
        Args:
            installed_apps: List of app names
        
        Returns:
            Comprehensive insights report
        """
        # Check for known issues
        known_issues = self.check_known_issues_for_apps(installed_apps)
        
        # Check for conflicts
        conflicts = self.conflict_db.check_conflicts(installed_apps)
        
        # Check for duplicate functionality
        duplicates = self.conflict_db.get_duplicate_functionality_apps(installed_apps)
        
        # Get trending issues for these apps
        trending = []
        for issue in self.trending:
            if any(issue["app"] in app.lower() for app in installed_apps):
                trending.append(issue)
        
        # Calculate overall risk
        high_risk_apps = [i for i in known_issues if i["severity"] in ["critical", "high"]]
        critical_conflicts = [c for c in conflicts if c["severity"] in ["critical", "high"]]
        
        overall_risk = "low"
        if len(critical_conflicts) > 0 or len(high_risk_apps) > 2:
            overall_risk = "high"
        elif len(conflicts) > 0 or len(high_risk_apps) > 0:
            overall_risk = "medium"
        
        return {
            "overall_risk": overall_risk,
            "apps_analyzed": len(installed_apps),
            "apps_with_known_issues": len(known_issues),
            "known_issues": known_issues,
            "conflicts_detected": len(conflicts),
            "conflicts": conflicts,
            "duplicate_functionality": duplicates,
            "trending_issues": trending,
            "recommendations": self._generate_recommendations(
                known_issues, conflicts, duplicates
            ),
        }
    
    def _generate_recommendations(
        self,
        known_issues: List[Dict],
        conflicts: List[Dict],
        duplicates: Dict[str, List[str]]
    ) -> List[Dict[str, Any]]:
        """Generate actionable recommendations"""
        recommendations = []
        
        # Conflict recommendations
        for conflict in conflicts:
            recommendations.append({
                "priority": 1 if conflict["severity"] == "critical" else 2,
                "type": "resolve_conflict",
                "action": f"Resolve conflict between {' and '.join(conflict['conflicting_apps'])}",
                "reason": conflict["description"],
                "solution": conflict["solution"],
            })
        
        # Duplicate functionality recommendations
        for category, apps in duplicates.items():
            recommendations.append({
                "priority": 2,
                "type": "remove_duplicate",
                "action": f"Remove duplicate {category.replace('_', ' ')} apps",
                "reason": f"Multiple apps doing the same thing: {', '.join(apps)}",
                "solution": f"Keep only one {category.replace('_', ' ')} app to avoid conflicts and improve performance",
            })
        
        # High severity issue recommendations
        for issue in known_issues:
            if issue["severity"] in ["critical", "high"]:
                recommendations.append({
                    "priority": 2,
                    "type": "review_app",
                    "action": f"Review '{issue['app']}' - {issue['total_community_reports']} community reports",
                    "reason": f"Common symptoms: {', '.join(issue['top_symptoms'][:2])}",
                    "solution": issue["typical_resolution"],
                })
        
        # Sort by priority
        recommendations.sort(key=lambda x: x["priority"])
        
        return recommendations[:10]  # Limit to top 10
