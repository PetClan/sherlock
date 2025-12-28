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
KNOWN_APPS_REGISTRY = {
    # Page Builders - HIGH RISK
    "pagefly": {"risk": 40, "category": "Page Builder", "reason": "Makes deep changes to your theme. If something goes wrong, your whole store can look broken."},
    "gempages": {"risk": 35, "category": "Page Builder", "reason": "Makes deep changes to your theme. If something goes wrong, your whole store can look broken."},
    "shogun": {"risk": 35, "category": "Page Builder", "reason": "Makes deep changes to your theme. If something goes wrong, your whole store can look broken."},
    
    # Reviews - LOW-MEDIUM RISK
    "loox": {"risk": 20, "category": "Reviews", "reason": "Usually safe. Adds some code to show stars and reviews on product pages."},
    "judge.me": {"risk": 15, "category": "Reviews", "reason": "Usually safe. Adds some code to show stars and reviews on product pages."},
    "yotpo": {"risk": 20, "category": "Reviews", "reason": "Usually safe. Adds some code to show stars and reviews on product pages."},
    "stamped": {"risk": 15, "category": "Reviews", "reason": "Usually safe. Adds some code to show stars and reviews on product pages."},
    
    # Marketing - MEDIUM RISK
    "klaviyo": {"risk": 15, "category": "Marketing", "reason": "Can add multiple scripts. Too many marketing apps can slow your store."},
    "omnisend": {"risk": 15, "category": "Marketing", "reason": "Can add multiple scripts. Too many marketing apps can slow your store."},
    "privy": {"risk": 25, "category": "Marketing", "reason": "Adds popups. Can conflict with other popup apps."},
    "justuno": {"risk": 25, "category": "Marketing", "reason": "Adds popups. Can conflict with other popup apps."},
    
    # Shipping - LOW RISK
    "aftership": {"risk": 10, "category": "Shipping", "reason": "Minimal impact. Usually just adds tracking info."},
    "hextom": {"risk": 10, "category": "Shipping", "reason": "Minimal impact. Usually just adds a small banner to your store."},
    
    # Subscriptions - HIGH RISK
    "recharge": {"risk": 30, "category": "Subscriptions", "reason": "Deeply integrated with checkout and payments. Complex apps that need careful setup."},
    "bold subscriptions": {"risk": 30, "category": "Subscriptions", "reason": "Deeply integrated with checkout and payments. Complex apps that need careful setup."},
    
    # Upsell - MEDIUM RISK
    "zipify": {"risk": 25, "category": "Upsell", "reason": "Adds elements to your pages. Too many upsell apps can clutter your store."},
    "reconvert": {"risk": 25, "category": "Upsell", "reason": "Adds elements to your pages. Too many upsell apps can clutter your store."},
    
    # Checkout - HIGH RISK
    "bold": {"risk": 20, "category": "Checkout", "reason": "The checkout is critical for sales. Problems here directly lose you money."},
    
    # Customer Service - LOW RISK
    "tidio": {"risk": 20, "category": "Customer Service", "reason": "Usually just adds a chat bubble. Rarely causes problems."},
    "gorgias": {"risk": 15, "category": "Customer Service", "reason": "Usually just adds a chat bubble. Rarely causes problems."},
    
    # Analytics - LOW RISK
    "facebook channel": {"risk": 15, "category": "Analytics", "reason": "Runs quietly in the background. Rarely causes visual issues."},
    "google channel": {"risk": 15, "category": "Analytics", "reason": "Runs quietly in the background. Rarely causes visual issues."},
    
    # Social Proof - MEDIUM RISK
    "instafeed": {"risk": 20, "category": "Social Proof", "reason": "Multiple social proof apps can create annoying popups and slow your store."},
    "smile": {"risk": 20, "category": "Social Proof", "reason": "Adds widgets and loyalty features to your store."},
    
    # Translation - MEDIUM RISK  
    "langify": {"risk": 25, "category": "Translation", "reason": "Changes text across your entire store. Can slow things down."},
    "weglot": {"risk": 25, "category": "Translation", "reason": "Changes text across your entire store. Can slow things down."},
    
    # Other
    "currency converter": {"risk": 35, "category": "Checkout", "reason": "Changes prices everywhere. Can cause checkout confusion."},
    "geolocation": {"risk": 30, "category": "Marketing", "reason": "Redirects visitors. Can cause loading delays."},
    "vitals": {"risk": 30, "category": "Marketing", "reason": "All-in-one app with many features. More features = more chances for conflicts."},
    "oberlo": {"risk": 15, "category": "Admin Only", "reason": "Works behind the scenes for dropshipping. Customers never see it."},
    "dsers": {"risk": 15, "category": "Admin Only", "reason": "Works behind the scenes for dropshipping. Customers never see it."},
}

# Keep old name for backwards compatibility
KNOWN_PROBLEMATIC_APPS = KNOWN_APPS_REGISTRY
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
                "source": "app_block",
                "app_name": app.get("app_name", "Unknown"),
                "app_handle": app.get("app_handle"),
                "disabled": app.get("disabled", False),
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
        """Fetch apps with theme extensions - now uses app blocks detection"""
        return await self._fetch_app_blocks_from_theme(store)
    
    async def _fetch_app_blocks_from_theme(self, store: Store) -> List[Dict]:
        """Fetch apps with app blocks from theme settings_data.json"""
        import json
        
        try:
            async with httpx.AsyncClient() as client:
                # Get main theme
                themes_response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/2024-01/themes.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if themes_response.status_code != 200:
                    print(f"⚠️ [AppScanner] Failed to fetch themes: {themes_response.status_code}")
                    return []
                
                themes = themes_response.json().get("themes", [])
                main_theme = next((t for t in themes if t.get("role") == "main"), None)
                
                if not main_theme:
                    return []
                
                theme_id = main_theme["id"]
                
                # Fetch settings_data.json
                settings_response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/2024-01/themes/{theme_id}/assets.json",
                    params={"asset[key]": "config/settings_data.json"},
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if settings_response.status_code != 200:
                    return []
                
                asset = settings_response.json().get("asset", {})
                settings_content = asset.get("value", "{}")
                
                try:
                    settings_data = json.loads(settings_content)
                except:
                    return []
                
                # Extract app blocks
                current = settings_data.get("current", {})
                blocks = current.get("blocks", {})
                
                apps_found = []
                seen_apps = set()
                
                for block_id, block_data in blocks.items():
                    block_type = block_data.get("type", "")
                    
                    # Pattern: shopify://apps/{app-handle}/blocks/{block-name}/{uuid}
                    if block_type.startswith("shopify://apps/"):
                        parts = block_type.split("/")
                        if len(parts) >= 4:
                            app_handle = parts[3]  # e.g., "judge-me-reviews"
                            
                            if app_handle not in seen_apps:
                                seen_apps.add(app_handle)
                                
                                # Convert handle to display name
                                app_name = self._handle_to_display_name(app_handle)
                                
                                apps_found.append({
                                    "source": "app_block",
                                    "app_name": app_name,
                                    "app_handle": app_handle,
                                    "disabled": block_data.get("disabled", False),
                                })
                
                print(f"✅ [AppScanner] Found {len(apps_found)} apps via app blocks")
                return apps_found
                
        except Exception as e:
            print(f"❌ [AppScanner] Error fetching app blocks: {e}")
            return []
    
    def _handle_to_display_name(self, handle: str) -> str:
        """Convert app handle to display name"""
        # Known app mappings
        known_apps = {
            "judge-me-reviews": "Judge.me",
            "hextom-shipping-bar": "Hextom Shipping Bar",
            "loox": "Loox",
            "klaviyo": "Klaviyo",
            "privy": "Privy",
            "pagefly": "PageFly",
            "gempages": "GemPages",
            "shogun": "Shogun",
            "omnisend": "Omnisend",
            "smile-io": "Smile.io",
            "yotpo": "Yotpo",
            "recharge": "ReCharge",
            "bold": "Bold",
        }
        
        if handle in known_apps:
            return known_apps[handle]
        
        # Convert handle to title case
        return handle.replace("-", " ").title()
    
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
        category = "Unknown"
        category_reason = "Sherlock is monitoring this app. No problems detected so far."
        
        app_name_lower = app_name.lower()
        
        # Check known apps registry for category and risk
        for known_app, info in KNOWN_APPS_REGISTRY.items():
            if known_app in app_name_lower:
                risk_score += info["risk"]
                risk_reasons.append(info["reason"])
                category = info.get("category", "Unknown")
                category_reason = info["reason"]
                break
        
        # Check high-risk categories in app name (fallback classification)
        if category == "Unknown":
            category_keywords = {
                "review": ("Reviews", "Usually safe. Adds some code to show stars and reviews on product pages."),
                "shipping": ("Shipping", "Minimal impact. Usually just adds a small banner to your store."),
                "marketing": ("Marketing", "Can add multiple scripts. Too many marketing apps can slow your store."),
                "email": ("Marketing", "Can add multiple scripts. Too many marketing apps can slow your store."),
                "sms": ("Marketing", "Can add multiple scripts. Too many marketing apps can slow your store."),
                "popup": ("Marketing", "Adds popups. Can conflict with other popup apps."),
                "analytics": ("Analytics", "Runs quietly in the background. Rarely causes visual issues."),
                "checkout": ("Checkout", "The checkout is critical for sales. Problems here directly lose you money."),
                "page builder": ("Page Builder", "Makes deep changes to your theme. If something goes wrong, your whole store can look broken."),
                "landing": ("Page Builder", "Makes deep changes to your theme. If something goes wrong, your whole store can look broken."),
                "seo": ("SEO", "Usually just adds invisible code for search engines."),
                "discount": ("Discounts", "Can conflict with other discount apps. Multiple discount apps often cause issues."),
                "upsell": ("Upsell", "Adds elements to your pages. Too many upsell apps can clutter your store."),
                "cross-sell": ("Upsell", "Adds elements to your pages. Too many upsell apps can clutter your store."),
                "chat": ("Customer Service", "Usually just adds a chat bubble. Rarely causes problems."),
                "help desk": ("Customer Service", "Usually just adds a chat bubble. Rarely causes problems."),
                "subscription": ("Subscriptions", "Deeply integrated with checkout and payments. Complex apps that need careful setup."),
                "trust": ("Trust Badges", "Simple images. Very unlikely to cause issues."),
                "badge": ("Trust Badges", "Simple images. Very unlikely to cause issues."),
                "instagram": ("Social Proof", "Multiple social proof apps can create annoying popups and slow your store."),
                "social": ("Social Proof", "Multiple social proof apps can create annoying popups and slow your store."),
                "translation": ("Translation", "Changes text across your entire store. Can slow things down."),
                "currency": ("Checkout", "Changes prices everywhere. Can cause checkout confusion."),
            }
            
            for keyword, (cat, reason) in category_keywords.items():
                if keyword in app_name_lower:
                    category = cat
                    category_reason = reason
                    risk_score += 15
                    risk_reasons.append(f"Detected as {cat} app")
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
            "is_suspect": risk_score >= 40,
            "category": category,
            "category_reason": category_reason
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
                app.injects_theme_code = app_data.get("source") == "app_block"
                app.category = risk_data["category"]
                app.category_reason = risk_data["category_reason"]
                app.last_scanned = datetime.utcnow()
            else:
                app = InstalledApp(
                    store_id=store.id,
                    app_name=app_name,
                    app_handle=app_name_lower.replace(" ", "-"),
                    installed_on=installed_on or datetime.utcnow(),  # Use current time if not available (first seen)
                    risk_score=risk_data["risk_score"],
                    risk_reasons=risk_data["risk_reasons"],
                    is_suspect=risk_data["is_suspect"],
                    injects_scripts=app_data.get("source") == "script_tag",
                    injects_theme_code=app_data.get("source") == "app_block",
                    category=risk_data["category"],
                    category_reason=risk_data["category_reason"],
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
