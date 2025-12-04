"""
Sherlock - App Scanner Service
Fetches installed apps from Shopify and calculates risk scores
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import httpx

from app.db.models import Store, InstalledApp


# Known problematic apps (frequently mentioned in Shopify communities as causing issues)
KNOWN_PROBLEMATIC_APPS = {
    "pagefly": {"risk": 40, "reason": "Heavy page builder - known to cause conflicts with themes"},
    "gempages": {"risk": 35, "reason": "Page builder - can slow down store and conflict with themes"},
    "shogun": {"risk": 35, "reason": "Page builder - requires careful theme integration"},
    "loox": {"risk": 20, "reason": "Review app - injects scripts on product pages"},
    "judge.me": {"risk": 15, "reason": "Review app - generally stable but adds scripts"},
    "klaviyo": {"risk": 15, "reason": "Email marketing - adds tracking scripts"},
    "privy": {"risk": 25, "reason": "Popup app - can conflict with other popups"},
    "justuno": {"risk": 25, "reason": "Popup/promotion app - heavy script injection"},
    "bold": {"risk": 20, "reason": "Bold apps often modify checkout and product pages"},
    "recharge": {"risk": 30, "reason": "Subscription app - deeply integrates with checkout"},
    "zipify": {"risk": 25, "reason": "Upsell app - modifies cart and checkout flow"},
    "reconvert": {"risk": 25, "reason": "Thank you page builder - post-purchase modifications"},
    "vitals": {"risk": 30, "reason": "All-in-one app - many features can cause conflicts"},
    "omnisend": {"risk": 15, "reason": "Email/SMS marketing - adds tracking scripts"},
    "smile": {"risk": 20, "reason": "Loyalty app - adds widgets and scripts"},
    "yotpo": {"risk": 20, "reason": "Reviews/loyalty - multiple script injections"},
    "stamped": {"risk": 15, "reason": "Reviews app - generally lightweight"},
    "aftership": {"risk": 10, "reason": "Tracking app - minimal frontend impact"},
    "oberlo": {"risk": 15, "reason": "Dropshipping - can slow product syncs"},
    "dsers": {"risk": 15, "reason": "Dropshipping - similar to Oberlo"},
    "currency converter": {"risk": 35, "reason": "Currency apps often cause checkout issues"},
    "geolocation": {"risk": 30, "reason": "Redirect apps can cause loading delays"},
    "langify": {"risk": 25, "reason": "Translation app - modifies all page content"},
    "weglot": {"risk": 25, "reason": "Translation app - intercepts page rendering"},
    "tidio": {"risk": 20, "reason": "Chat widget - adds external scripts"},
    "gorgias": {"risk": 15, "reason": "Help desk - chat widget integration"},
    "instafeed": {"risk": 20, "reason": "Instagram feed - external API calls"},
    "facebook channel": {"risk": 15, "reason": "Meta integration - pixel and catalog sync"},
    "google channel": {"risk": 15, "reason": "Google integration - tracking and feed sync"},
}

# App categories that commonly cause specific issues
HIGH_RISK_CATEGORIES = [
    "page builder",
    "landing page",
    "popup",
    "currency",
    "translation",
    "upsell",
    "cross-sell",
    "subscription",
    "countdown",
    "timer",
]


class AppScannerService:
    """Service for scanning and analyzing installed Shopify apps"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def fetch_apps_from_shopify(self, store: Store) -> List[Dict[str, Any]]:
        """
        Fetch installed apps from Shopify Admin API
        
        Note: Shopify's API has limited app visibility. We can get:
        - Script tags (apps that inject scripts)
        - Theme app extensions
        - App metafields
        
        For full app list, we'd need the merchant to grant additional permissions
        or use the Partners API (if we're the app developer).
        """
        if not store.access_token:
            print(f"⚠️ [AppScanner] No access token for {store.shopify_domain}")
            return []
        
        apps = []
        
        # Fetch script tags (apps that inject JavaScript)
        script_tags = await self._fetch_script_tags(store)
        for tag in script_tags:
            apps.append({
                "source": "script_tag",
                "app_name": self._extract_app_name_from_url(tag.get("src", "")),
                "script_url": tag.get("src"),
                "display_scope": tag.get("display_scope"),
                "created_at": tag.get("created_at"),
            })
        
        # Fetch theme app blocks (apps with theme extensions)
        theme_apps = await self._fetch_theme_app_extensions(store)
        for app in theme_apps:
            apps.append({
                "source": "theme_extension",
                "app_name": app.get("name", "Unknown"),
                "app_id": app.get("id"),
            })
        
        return apps
    
    async def _fetch_script_tags(self, store: Store) -> List[Dict]:
        """Fetch all script tags from Shopify"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/2024-01/script_tags.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("script_tags", [])
                else:
                    print(f"⚠️ [AppScanner] Script tags API error: {response.status_code}")
                    return []
        except Exception as e:
            print(f"❌ [AppScanner] Error fetching script tags: {e}")
            return []
    
    async def _fetch_theme_app_extensions(self, store: Store) -> List[Dict]:
        """Fetch apps with theme extensions"""
        # This requires parsing the theme to find app blocks
        # For now, return empty - will be enhanced in theme_analyzer
        return []
    
    def _extract_app_name_from_url(self, url: str) -> str:
        """Extract app name from script URL"""
        if not url:
            return "Unknown"
        
        url_lower = url.lower()
        
        # Common patterns
        known_domains = {
            "pagefly": "PageFly",
            "gempages": "GemPages",
            "shogun": "Shogun",
            "loox": "Loox",
            "judge.me": "Judge.me",
            "judgeme": "Judge.me",
            "klaviyo": "Klaviyo",
            "privy": "Privy",
            "justuno": "JustUno",
            "bold": "Bold",
            "recharge": "ReCharge",
            "zipify": "Zipify",
            "reconvert": "ReConvert",
            "vitals": "Vitals",
            "omnisend": "Omnisend",
            "smile": "Smile.io",
            "yotpo": "Yotpo",
            "stamped": "Stamped.io",
            "aftership": "AfterShip",
            "tidio": "Tidio",
            "gorgias": "Gorgias",
            "instafeed": "Instafeed",
            "weglot": "Weglot",
            "langify": "Langify",
        }
        
        for key, name in known_domains.items():
            if key in url_lower:
                return name
        
        # Try to extract from domain
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "").split(".")[0]
            return domain.title()
        except:
            return "Unknown"
    
    async def calculate_risk_score(self, app_name: str, installed_on: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Calculate risk score for an app based on:
        1. Known problematic apps list
        2. How recently it was installed (newer = higher risk)
        3. App category patterns
        """
        risk_score = 0.0
        risk_reasons = []
        
        app_name_lower = app_name.lower()
        
        # Check known problematic apps
        for known_app, info in KNOWN_PROBLEMATIC_APPS.items():
            if known_app in app_name_lower:
                risk_score += info["risk"]
                risk_reasons.append(info["reason"])
                break
        
        # Check high-risk categories
        for category in HIGH_RISK_CATEGORIES:
            if category in app_name_lower:
                risk_score += 15
                risk_reasons.append(f"App appears to be a {category} - commonly causes conflicts")
                break
        
        # Recently installed apps are more likely to be the cause
        if installed_on:
            days_ago = (datetime.utcnow() - installed_on).days
            if days_ago <= 1:
                risk_score += 30
                risk_reasons.append("Installed in the last 24 hours - highly suspect")
            elif days_ago <= 3:
                risk_score += 25
                risk_reasons.append("Installed in the last 3 days - likely suspect")
            elif days_ago <= 7:
                risk_score += 20
                risk_reasons.append("Installed in the last week - possible suspect")
            elif days_ago <= 14:
                risk_score += 10
                risk_reasons.append("Installed in the last 2 weeks")
        
        # Cap at 100
        risk_score = min(risk_score, 100.0)
        
        return {
            "risk_score": risk_score,
            "risk_reasons": risk_reasons,
            "is_suspect": risk_score >= 40
        }
    
    async def scan_store_apps(self, store: Store) -> Dict[str, Any]:
        """
        Full app scan for a store:
        1. Fetch apps from Shopify
        2. Calculate risk scores
        3. Store results in database
        4. Return summary
        """
        print(f"🔍 [AppScanner] Scanning apps for {store.shopify_domain}")
        
        # Fetch apps from Shopify
        shopify_apps = await self.fetch_apps_from_shopify(store)
        
        # Get existing apps from database
        result = await self.db.execute(
            select(InstalledApp).where(InstalledApp.store_id == store.id)
        )
        existing_apps = {app.app_name.lower(): app for app in result.scalars().all()}
        
        scanned_apps = []
        suspects = []
        
        for app_data in shopify_apps:
            app_name = app_data.get("app_name", "Unknown")
            app_name_lower = app_name.lower()
            
            # Parse install date
            installed_on = None
            if app_data.get("created_at"):
                try:
                    installed_on = datetime.fromisoformat(
                        app_data["created_at"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except:
                    pass
            
            # Calculate risk
            risk_data = await self.calculate_risk_score(app_name, installed_on)
            
            # Update or create app record
            if app_name_lower in existing_apps:
                app = existing_apps[app_name_lower]
                app.risk_score = risk_data["risk_score"]
                app.risk_reasons = risk_data["risk_reasons"]
                app.is_suspect = risk_data["is_suspect"]
                app.injects_scripts = app_data.get("source") == "script_tag"
                app.last_scanned = datetime.utcnow()
            else:
                app = InstalledApp(
                    store_id=store.id,
                    app_name=app_name,
                    app_handle=app_name_lower.replace(" ", "-"),
                    installed_on=installed_on,
                    risk_score=risk_data["risk_score"],
                    risk_reasons=risk_data["risk_reasons"],
                    is_suspect=risk_data["is_suspect"],
                    injects_scripts=app_data.get("source") == "script_tag",
                    last_scanned=datetime.utcnow()
                )
                self.db.add(app)
            
            scanned_apps.append({
                "app_name": app_name,
                "risk_score": risk_data["risk_score"],
                "is_suspect": risk_data["is_suspect"],
                "risk_reasons": risk_data["risk_reasons"]
            })
            
            if risk_data["is_suspect"]:
                suspects.append(app_name)
        
        await self.db.flush()
        
        # Sort by risk score
        scanned_apps.sort(key=lambda x: x["risk_score"], reverse=True)
        
        print(f"✅ [AppScanner] Found {len(scanned_apps)} apps, {len(suspects)} suspects")
        
        return {
            "total_apps": len(scanned_apps),
            "suspect_count": len(suspects),
            "suspects": suspects,
            "apps": scanned_apps
        }
    
    async def get_recently_installed_apps(self, store: Store, days: int = 7) -> List[InstalledApp]:
        """Get apps installed within the last N days"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store.id)
            .where(InstalledApp.installed_on >= cutoff)
            .order_by(InstalledApp.installed_on.desc())
        )
        
        return list(result.scalars().all())
    
    async def get_suspect_apps(self, store: Store) -> List[InstalledApp]:
        """Get all apps flagged as suspects"""
        result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store.id)
            .where(InstalledApp.is_suspect == True)
            .order_by(InstalledApp.risk_score.desc())
        )
        
        return list(result.scalars().all())
