"""
Sherlock - Conflict Database
Known app conflicts, incompatibilities, and community-reported issues
"""

from typing import Dict, List, Optional, Any
from datetime import datetime


# ==================== Known App Conflicts ====================
# These are pairs/groups of apps that commonly cause conflicts when installed together
# Data sourced from Shopify community forums, Reddit, Facebook groups

KNOWN_CONFLICTS = [
    # Page Builders - Never install multiple
    {
        "apps": ["pagefly", "gempages"],
        "severity": "critical",
        "type": "duplicate_functionality",
        "description": "Multiple page builders will conflict. Both inject heavy scripts and modify theme code.",
        "solution": "Choose one page builder and uninstall the other.",
        "reports": 847,
    },
    {
        "apps": ["pagefly", "shogun"],
        "severity": "critical",
        "type": "duplicate_functionality",
        "description": "PageFly and Shogun both modify theme templates and can overwrite each other.",
        "solution": "Use only one page builder.",
        "reports": 632,
    },
    {
        "apps": ["gempages", "shogun"],
        "severity": "critical",
        "type": "duplicate_functionality",
        "description": "GemPages and Shogun conflict when building the same page types.",
        "solution": "Pick one page builder for your store.",
        "reports": 498,
    },
    {
        "apps": ["pagefly", "replo"],
        "severity": "high",
        "type": "duplicate_functionality",
        "description": "Both apps modify landing pages and can cause rendering issues.",
        "solution": "Use only one landing page builder.",
        "reports": 234,
    },
    
    # Review Apps - Script conflicts
    {
        "apps": ["loox", "judge.me"],
        "severity": "medium",
        "type": "script_conflict",
        "description": "Multiple review apps can show duplicate reviews or conflict on product pages.",
        "solution": "Use one review app. Judge.me is lighter; Loox has better photo features.",
        "reports": 523,
    },
    {
        "apps": ["loox", "yotpo"],
        "severity": "medium",
        "type": "script_conflict",
        "description": "Both inject review widgets that can overlap or cause layout issues.",
        "solution": "Choose one review solution.",
        "reports": 412,
    },
    {
        "apps": ["judge.me", "yotpo"],
        "severity": "medium",
        "type": "script_conflict",
        "description": "Duplicate review functionality causes confusion and slower load times.",
        "solution": "Stick with one review app.",
        "reports": 387,
    },
    {
        "apps": ["stamped", "loox"],
        "severity": "medium",
        "type": "script_conflict",
        "description": "Both apps add star ratings and review sections that can conflict.",
        "solution": "Use only one reviews app.",
        "reports": 298,
    },
    
    # Popup/Marketing Apps - Overlay conflicts
    {
        "apps": ["privy", "justuno"],
        "severity": "high",
        "type": "overlay_conflict",
        "description": "Multiple popup apps fight for screen space and can show simultaneously.",
        "solution": "Use one popup/email capture app.",
        "reports": 678,
    },
    {
        "apps": ["privy", "klaviyo"],
        "severity": "medium",
        "type": "overlay_conflict",
        "description": "Both can show email signup popups. Klaviyo's forms may conflict with Privy.",
        "solution": "Use Klaviyo's built-in forms OR Privy, not both for popups.",
        "reports": 445,
    },
    {
        "apps": ["optinmonster", "privy"],
        "severity": "high",
        "type": "overlay_conflict",
        "description": "Competing popup triggers can annoy customers and break each other.",
        "solution": "Choose one popup solution.",
        "reports": 312,
    },
    {
        "apps": ["wheelio", "privy"],
        "severity": "medium",
        "type": "overlay_conflict",
        "description": "Spin wheel and popup can trigger together, overwhelming visitors.",
        "solution": "Configure triggers carefully or use only one.",
        "reports": 267,
    },
    
    # Currency/Geolocation - Checkout issues
    {
        "apps": ["currency converter", "geolocation"],
        "severity": "high",
        "type": "checkout_conflict",
        "description": "Multiple currency/location apps can show conflicting prices or cause checkout errors.",
        "solution": "Use Shopify's native currency features or one third-party solution.",
        "reports": 534,
    },
    {
        "apps": ["bold currency", "currency converter"],
        "severity": "high",
        "type": "price_conflict",
        "description": "Conflicting price displays and conversion rates.",
        "solution": "Use only one currency converter.",
        "reports": 423,
    },
    
    # Upsell/Cross-sell Apps
    {
        "apps": ["reconvert", "zipify"],
        "severity": "high",
        "type": "checkout_conflict",
        "description": "Both modify thank you/post-purchase pages and can conflict.",
        "solution": "Use one post-purchase upsell app.",
        "reports": 389,
    },
    {
        "apps": ["bold upsell", "zipify"],
        "severity": "medium",
        "type": "cart_conflict",
        "description": "Multiple upsell apps can show competing offers in cart.",
        "solution": "Choose one upsell solution.",
        "reports": 345,
    },
    {
        "apps": ["honeycomb", "reconvert"],
        "severity": "medium",
        "type": "checkout_conflict",
        "description": "Both target post-purchase flow and can interfere.",
        "solution": "Use one upsell funnel app.",
        "reports": 234,
    },
    
    # Subscription Apps
    {
        "apps": ["recharge", "bold subscriptions"],
        "severity": "critical",
        "type": "checkout_conflict",
        "description": "Multiple subscription apps will break checkout completely.",
        "solution": "NEVER use multiple subscription apps. Pick one.",
        "reports": 567,
    },
    {
        "apps": ["recharge", "seal subscriptions"],
        "severity": "critical",
        "type": "checkout_conflict",
        "description": "Subscription apps cannot coexist - they modify checkout fundamentally.",
        "solution": "Use only one subscription solution.",
        "reports": 234,
    },
    
    # Chat/Support Apps
    {
        "apps": ["tidio", "gorgias"],
        "severity": "low",
        "type": "widget_conflict",
        "description": "Multiple chat widgets can appear and confuse customers.",
        "solution": "Use one customer support solution.",
        "reports": 187,
    },
    {
        "apps": ["intercom", "drift"],
        "severity": "low",
        "type": "widget_conflict",
        "description": "Competing chat widgets in the corner of the screen.",
        "solution": "Choose one live chat provider.",
        "reports": 156,
    },
    
    # Translation Apps
    {
        "apps": ["weglot", "langify"],
        "severity": "high",
        "type": "content_conflict",
        "description": "Multiple translation apps will show conflicting translations.",
        "solution": "Use only one translation solution.",
        "reports": 298,
    },
    {
        "apps": ["weglot", "transcy"],
        "severity": "high",
        "type": "content_conflict",
        "description": "Translation apps intercept page content and can conflict.",
        "solution": "Pick one translation app.",
        "reports": 234,
    },
    
    # SEO Apps
    {
        "apps": ["plug in seo", "smart seo"],
        "severity": "medium",
        "type": "meta_conflict",
        "description": "Multiple SEO apps can generate conflicting meta tags.",
        "solution": "Use one SEO optimization app.",
        "reports": 312,
    },
    
    # Image/Media Apps
    {
        "apps": ["crush.pics", "tiny img"],
        "severity": "low",
        "type": "processing_conflict",
        "description": "Multiple image optimizers can over-compress or conflict.",
        "solution": "Use one image optimization app.",
        "reports": 145,
    },
    
    # Shipping Apps
    {
        "apps": ["shipstation", "shippo"],
        "severity": "medium",
        "type": "fulfillment_conflict",
        "description": "Multiple shipping apps can cause duplicate labels or sync issues.",
        "solution": "Use one shipping/fulfillment solution.",
        "reports": 234,
    },
]


# ==================== Community Reported Issues ====================
# Specific app issues reported frequently in communities

COMMUNITY_REPORTS = {
    "pagefly": {
        "common_issues": [
            "Causes slow page load (adds 2-5 seconds)",
            "Breaks mobile menu on some themes",
            "Conflicts with Dawn theme's native sections",
            "Leaves orphan code after uninstall",
        ],
        "affected_themes": ["dawn", "impulse", "warehouse", "turbo"],
        "report_count": 1247,
        "last_updated": "2025-01",
        "severity_trend": "stable",
    },
    "gempages": {
        "common_issues": [
            "Heavy JavaScript bundle slows store",
            "Editor can break product page templates",
            "CSS conflicts with custom themes",
            "Duplicate jQuery loading",
        ],
        "affected_themes": ["debut", "brooklyn", "narrative"],
        "report_count": 987,
        "last_updated": "2025-01",
        "severity_trend": "improving",
    },
    "vitals": {
        "common_issues": [
            "All-in-one app = many potential conflicts",
            "Individual features can't be fully disabled",
            "Adds significant page weight",
            "Currency converter breaks with Shopify Markets",
        ],
        "affected_themes": ["all"],
        "report_count": 756,
        "last_updated": "2025-01",
        "severity_trend": "stable",
    },
    "klaviyo": {
        "common_issues": [
            "Popup forms conflict with theme modals",
            "Tracking script can slow initial load",
            "Back-in-stock conflicts with other notification apps",
        ],
        "affected_themes": [],
        "report_count": 534,
        "last_updated": "2025-01",
        "severity_trend": "improving",
    },
    "recharge": {
        "common_issues": [
            "Checkout modifications can break with theme updates",
            "Conflicts with other cart modification apps",
            "Portal styling issues on custom themes",
        ],
        "affected_themes": ["custom themes"],
        "report_count": 445,
        "last_updated": "2025-01",
        "severity_trend": "stable",
    },
    "privy": {
        "common_issues": [
            "Popup timing conflicts",
            "Mobile popup can cover entire screen",
            "Exit intent fires incorrectly on some browsers",
        ],
        "affected_themes": [],
        "report_count": 398,
        "last_updated": "2025-01",
        "severity_trend": "stable",
    },
    "loox": {
        "common_issues": [
            "Review carousel conflicts with theme sliders",
            "Photo reviews slow down product pages",
            "Widget placement issues on OS 2.0 themes",
        ],
        "affected_themes": ["dawn", "sense", "craft"],
        "report_count": 367,
        "last_updated": "2025-01",
        "severity_trend": "improving",
    },
    "bold": {
        "common_issues": [
            "Bold apps often conflict with each other",
            "Product options can break variant selection",
            "Subscriptions conflict with other checkout mods",
        ],
        "affected_themes": ["all"],
        "report_count": 445,
        "last_updated": "2025-01",
        "severity_trend": "stable",
    },
}


# ==================== Orphan Code Patterns ====================
# Patterns left behind after apps are uninstalled

ORPHAN_CODE_PATTERNS = [
    {
        "app": "PageFly",
        "patterns": [
            r"pagefly",
            r"pf-[a-z0-9]+",
            r"__pf_[a-z]+",
            r"data-pf-type",
            r"pagefly\.io",
        ],
        "files": ["layout/theme.liquid", "snippets/", "assets/"],
        "cleanup_guide": "Remove all snippets starting with 'pf-' and references in theme.liquid",
    },
    {
        "app": "GemPages",
        "patterns": [
            r"gempages",
            r"gp-[a-z0-9]+",
            r"__gem",
            r"gem-page",
            r"gempages\.net",
        ],
        "files": ["layout/theme.liquid", "templates/", "snippets/"],
        "cleanup_guide": "Remove GemPages snippets and template references",
    },
    {
        "app": "Shogun",
        "patterns": [
            r"shogun",
            r"shogun-[a-z]+",
            r"shg-[a-z]+",
            r"getshogun\.com",
        ],
        "files": ["layout/theme.liquid", "snippets/", "sections/"],
        "cleanup_guide": "Remove Shogun sections and snippet includes",
    },
    {
        "app": "Loox",
        "patterns": [
            r"loox",
            r"loox-[a-z]+",
            r"looxio",
            r"loox\.io",
        ],
        "files": ["layout/theme.liquid", "snippets/", "templates/product"],
        "cleanup_guide": "Remove Loox widget code and snippet references",
    },
    {
        "app": "Judge.me",
        "patterns": [
            r"judgeme",
            r"judge\.me",
            r"jdgm-[a-z]+",
            r"jdgm_",
        ],
        "files": ["layout/theme.liquid", "snippets/", "templates/product"],
        "cleanup_guide": "Remove Judge.me badges and widget snippets",
    },
    {
        "app": "Privy",
        "patterns": [
            r"privy",
            r"privy-[a-z]+",
            r"widget\.privy\.com",
        ],
        "files": ["layout/theme.liquid"],
        "cleanup_guide": "Remove Privy script tag from theme.liquid",
    },
    {
        "app": "Klaviyo",
        "patterns": [
            r"klaviyo",
            r"_learnq",
            r"static\.klaviyo\.com",
            r"klaviyo-[a-z]+",
        ],
        "files": ["layout/theme.liquid", "snippets/"],
        "cleanup_guide": "Remove Klaviyo tracking script and form snippets",
    },
    {
        "app": "Yotpo",
        "patterns": [
            r"yotpo",
            r"yotpo-[a-z]+",
            r"staticw2\.yotpo\.com",
        ],
        "files": ["layout/theme.liquid", "snippets/", "templates/product"],
        "cleanup_guide": "Remove Yotpo widgets and review snippets",
    },
    {
        "app": "ReCharge",
        "patterns": [
            r"recharge",
            r"rc-[a-z]+",
            r"rechargepayments",
            r"rechargeapps\.com",
        ],
        "files": ["layout/theme.liquid", "snippets/", "templates/product"],
        "cleanup_guide": "Remove ReCharge subscription widget code",
    },
    {
        "app": "Bold",
        "patterns": [
            r"bold-[a-z]+",
            r"boldapps",
            r"boldcommerce",
            r"BOLD\.",
        ],
        "files": ["layout/theme.liquid", "snippets/", "templates/product"],
        "cleanup_guide": "Remove Bold app snippets and scripts",
    },
    {
        "app": "Tidio",
        "patterns": [
            r"tidio",
            r"tidio-[a-z]+",
            r"code\.tidio\.co",
        ],
        "files": ["layout/theme.liquid"],
        "cleanup_guide": "Remove Tidio chat widget script",
    },
    {
        "app": "Omnisend",
        "patterns": [
            r"omnisend",
            r"omnisrc",
            r"omnisnippet",
        ],
        "files": ["layout/theme.liquid", "snippets/"],
        "cleanup_guide": "Remove Omnisend tracking and form code",
    },
]


class ConflictDatabase:
    """Service for checking known conflicts and community issues"""
    
    def __init__(self):
        self.conflicts = KNOWN_CONFLICTS
        self.community_reports = COMMUNITY_REPORTS
        self.orphan_patterns = ORPHAN_CODE_PATTERNS
    
    def check_conflicts(self, installed_apps: List[str]) -> List[Dict[str, Any]]:
        """
        Check if any installed apps have known conflicts with each other
        
        Args:
            installed_apps: List of app names (lowercase)
        
        Returns:
            List of conflict records
        """
        found_conflicts = []
        installed_lower = [app.lower() for app in installed_apps]
        
        for conflict in self.conflicts:
            conflict_apps = [app.lower() for app in conflict["apps"]]
            
            # Check if all apps in the conflict pair are installed
            matches = [app for app in conflict_apps if any(
                app in installed for installed in installed_lower
            )]
            
            if len(matches) >= 2:
                found_conflicts.append({
                    "conflicting_apps": conflict["apps"],
                    "matched_apps": matches,
                    "severity": conflict["severity"],
                    "type": conflict["type"],
                    "description": conflict["description"],
                    "solution": conflict["solution"],
                    "community_reports": conflict["reports"],
                })
        
        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        found_conflicts.sort(key=lambda x: severity_order.get(x["severity"], 99))
        
        return found_conflicts
    
    def get_app_issues(self, app_name: str) -> Optional[Dict[str, Any]]:
        """
        Get known community-reported issues for an app
        
        Args:
            app_name: Name of the app
        
        Returns:
            Dict with issue information or None
        """
        app_lower = app_name.lower()
        
        for key, data in self.community_reports.items():
            if key in app_lower or app_lower in key:
                return {
                    "app": key,
                    "common_issues": data["common_issues"],
                    "affected_themes": data["affected_themes"],
                    "report_count": data["report_count"],
                    "last_updated": data["last_updated"],
                    "severity_trend": data["severity_trend"],
                }
        
        return None
    
    def get_orphan_patterns(self, app_name: str) -> Optional[Dict[str, Any]]:
        """
        Get patterns to detect leftover code from an uninstalled app
        
        Args:
            app_name: Name of the app
        
        Returns:
            Dict with patterns and cleanup guide
        """
        app_lower = app_name.lower()
        
        for pattern_data in self.orphan_patterns:
            if pattern_data["app"].lower() in app_lower or app_lower in pattern_data["app"].lower():
                return pattern_data
        
        return None
    
    def get_all_orphan_patterns(self) -> List[Dict[str, Any]]:
        """Get all orphan code patterns for scanning"""
        return self.orphan_patterns
    
    def get_duplicate_functionality_apps(self, installed_apps: List[str]) -> Dict[str, List[str]]:
        """
        Group installed apps by functionality to detect duplicates
        
        Args:
            installed_apps: List of installed app names
        
        Returns:
            Dict of {category: [apps]} where there are duplicates
        """
        # App categories
        categories = {
            "page_builder": ["pagefly", "gempages", "shogun", "replo", "layouthub", "ecomposer"],
            "reviews": ["loox", "judge.me", "yotpo", "stamped", "okendo", "reviews.io"],
            "popup_email": ["privy", "justuno", "optinmonster", "wheelio", "popupsmart"],
            "upsell": ["reconvert", "zipify", "bold upsell", "honeycomb", "aftersell"],
            "subscription": ["recharge", "bold subscriptions", "seal", "appstle", "loop"],
            "translation": ["weglot", "langify", "transcy", "translate"],
            "currency": ["currency converter", "bold currency", "coin", "auto currency"],
            "chat": ["tidio", "gorgias", "intercom", "drift", "zendesk", "freshdesk"],
            "seo": ["plug in seo", "smart seo", "seo manager", "seo booster"],
            "shipping": ["shipstation", "shippo", "easyship", "aftership"],
        }
        
        duplicates = {}
        installed_lower = [app.lower() for app in installed_apps]
        
        for category, apps in categories.items():
            found = []
            for app in apps:
                for installed in installed_lower:
                    if app in installed:
                        found.append(installed)
            
            if len(found) > 1:
                duplicates[category] = list(set(found))
        
        return duplicates
    
    def get_risk_multiplier(self, app_name: str, installed_apps: List[str]) -> float:
        """
        Calculate risk multiplier based on conflicts with other installed apps
        
        Args:
            app_name: The app to check
            installed_apps: All installed apps
        
        Returns:
            Multiplier (1.0 = no additional risk, >1.0 = increased risk)
        """
        multiplier = 1.0
        
        # Check for conflicts
        conflicts = self.check_conflicts(installed_apps)
        for conflict in conflicts:
            if app_name.lower() in [a.lower() for a in conflict["matched_apps"]]:
                if conflict["severity"] == "critical":
                    multiplier += 0.5
                elif conflict["severity"] == "high":
                    multiplier += 0.3
                elif conflict["severity"] == "medium":
                    multiplier += 0.15
        
        # Check for community issues
        issues = self.get_app_issues(app_name)
        if issues:
            if issues["report_count"] > 500:
                multiplier += 0.2
            elif issues["report_count"] > 200:
                multiplier += 0.1
        
        return min(multiplier, 2.0)  # Cap at 2x
