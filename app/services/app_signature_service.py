"""
Sherlock - App Signature Learning Service
Automatically learns to identify apps from script domains
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from urllib.parse import urlparse

from app.db.models import AppSignature, AppSignatureSighting, InstalledApp


# Whitelist - legitimate scripts to ignore (not app-related)
WHITELISTED_DOMAINS = [
    # Shopify
    "cdn.shopify.com",
    "shopify.com",
    "myshopify.com",
    
    # Google
    "google-analytics.com",
    "googletagmanager.com",
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "googleadservices.com",
    "googlesyndication.com",
    
    # Facebook/Meta
    "facebook.com",
    "facebook.net",
    "fbcdn.net",
    "connect.facebook.net",
    
    # Common CDNs (not app-specific)
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "ajax.googleapis.com",
    "code.jquery.com",
    
    # Analytics & common tools
    "js.stripe.com",
    "checkout.stripe.com",
    "snap.licdn.com",
    "platform.twitter.com",
    "static.hotjar.com",
    "script.hotjar.com",
    "bat.bing.com",
    "ct.pinterest.com",
    "static.ads-twitter.com",
    "www.clarity.ms",
    "tiktok.com",
    "analytics.tiktok.com",
]

# Hardcoded known apps (starting knowledge)
KNOWN_APP_PATTERNS = {
    "klaviyo": "Klaviyo",
    "pagefly": "PageFly",
    "gempages": "GemPages",
    "shogun": "Shogun",
    "loox": "Loox",
    "judge.me": "Judge.me",
    "judgeme": "Judge.me",
    "privy": "Privy",
    "justuno": "JustUno",
    "bold": "Bold",
    "recharge": "ReCharge",
    "zipify": "Zipify",
    "vitals": "Vitals",
    "omnisend": "Omnisend",
    "yotpo": "Yotpo",
    "stamped": "Stamped",
    "tidio": "Tidio",
    "gorgias": "Gorgias",
    "weglot": "Weglot",
    "langify": "Langify",
    "swell": "Swell Rewards",
    "smile": "Smile.io",
    "trustpilot": "Trustpilot",
    "aftership": "AfterShip",
    "returnly": "Returnly",
    "mailchimp": "Mailchimp",
    "hubspot": "HubSpot",
    "intercom": "Intercom",
    "zendesk": "Zendesk",
    "crisp": "Crisp",
    "drift": "Drift",
    "livechat": "LiveChat",
    "tawk": "Tawk.to",
    "okendo": "Okendo",
    "reviews.io": "Reviews.io",
    "trustoo": "Trustoo",
    "alireviews": "Ali Reviews",
    "dsers": "DSers",
    "oberlo": "Oberlo",
    "spocket": "Spocket",
    "printful": "Printful",
    "printify": "Printify",
    "gooten": "Gooten",
}


class AppSignatureService:
    """Service for learning and identifying app signatures"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    def extract_domain(self, url: str) -> Optional[str]:
        """Extract domain from a URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain if domain else None
        except:
            return None
    
    def is_whitelisted(self, domain: str) -> bool:
        """Check if domain is in whitelist (should be ignored)"""
        domain_lower = domain.lower()
        for whitelisted in WHITELISTED_DOMAINS:
            if whitelisted in domain_lower or domain_lower.endswith(whitelisted):
                return True
        return False
    
    def check_hardcoded(self, domain: str) -> Optional[str]:
        """Check if domain matches hardcoded known patterns"""
        domain_lower = domain.lower()
        for pattern, app_name in KNOWN_APP_PATTERNS.items():
            if pattern in domain_lower:
                return app_name
        return None
    
    async def check_learned(self, domain: str) -> Optional[Tuple[str, float]]:
        """Check if domain is in learned signatures database"""
        result = await self.db.execute(
            select(AppSignature)
            .where(AppSignature.domain == domain.lower())
            .where(AppSignature.confidence >= 50.0)
        )
        signature = result.scalar_one_or_none()
        
        if signature:
            return (signature.app_name, signature.confidence)
        return None
    
    def match_to_installed_apps(self, domain: str, installed_apps: List[str]) -> Optional[Tuple[str, float]]:
        """Try to match domain to an installed app by name similarity"""
        domain_lower = domain.lower()
        
        for app_name in installed_apps:
            app_lower = app_name.lower()
            # Remove common suffixes
            app_clean = app_lower.replace(" app", "").replace(" - ", "").replace("-", "").replace(" ", "")
            
            # Check if app name appears in domain
            if app_clean in domain_lower:
                return (app_name, 75.0)
            
            # Check if domain contains significant part of app name (3+ chars)
            if len(app_clean) >= 3 and app_clean[:3] in domain_lower:
                # Partial match - lower confidence
                return (app_name, 50.0)
        
        return None
    
    async def identify_script(
        self, 
        url: str, 
        store_id: str,
        installed_apps: List[str]
    ) -> Dict[str, Any]:
        """
        Identify what app a script belongs to.
        Returns: {app_name, confidence, source, domain}
        """
        domain = self.extract_domain(url)
        
        if not domain:
            return {"app_name": None, "confidence": 0, "source": "invalid", "domain": None}
        
        # 1. Check whitelist
        if self.is_whitelisted(domain):
            return {"app_name": None, "confidence": 100, "source": "whitelisted", "domain": domain}
        
        # 2. Check hardcoded known patterns
        hardcoded_match = self.check_hardcoded(domain)
        if hardcoded_match:
            # Record this sighting
            await self._record_sighting(domain, hardcoded_match, store_id, installed_apps, "hardcoded", 95.0)
            return {"app_name": hardcoded_match, "confidence": 95, "source": "known", "domain": domain}
        
        # 3. Check learned patterns
        learned_match = await self.check_learned(domain)
        if learned_match:
            app_name, confidence = learned_match
            await self._record_sighting(domain, app_name, store_id, installed_apps, "learned", confidence)
            return {"app_name": app_name, "confidence": confidence, "source": "learned", "domain": domain}
        
        # 4. Try to match to installed apps
        installed_match = self.match_to_installed_apps(domain, installed_apps)
        if installed_match:
            app_name, confidence = installed_match
            # This is a new learning - save it!
            await self._learn_signature(domain, app_name, store_id, installed_apps, confidence)
            return {"app_name": app_name, "confidence": confidence, "source": "matched", "domain": domain}
        
        # 5. Unknown - record for future learning
        await self._record_unknown(domain, store_id, installed_apps)
        return {"app_name": None, "confidence": 0, "source": "unknown", "domain": domain}
    
    async def _record_sighting(
        self, 
        domain: str, 
        app_name: str, 
        store_id: str, 
        installed_apps: List[str],
        source: str,
        confidence: float
    ):
        """Record a sighting of a known signature"""
        # Find or create signature
        result = await self.db.execute(
            select(AppSignature).where(AppSignature.domain == domain.lower())
        )
        signature = result.scalar_one_or_none()
        
        if signature:
            # Update existing
            signature.times_seen += 1
            signature.last_seen = datetime.utcnow()
            
            # Check if this is a new store
            existing_sighting = await self.db.execute(
                select(AppSignatureSighting)
                .where(AppSignatureSighting.signature_id == signature.id)
                .where(AppSignatureSighting.store_id == store_id)
            )
            if not existing_sighting.scalar_one_or_none():
                signature.stores_seen += 1
                
                # Increase confidence with more stores (max 95)
                if signature.confidence < 95:
                    signature.confidence = min(95, signature.confidence + 5)
        else:
            # Create new
            signature = AppSignature(
                domain=domain.lower(),
                app_name=app_name,
                confidence=confidence,
                is_from_hardcoded=(source == "hardcoded")
            )
            self.db.add(signature)
            await self.db.flush()
        
        # Record sighting
        sighting = AppSignatureSighting(
            signature_id=signature.id,
            store_id=store_id,
            installed_apps=installed_apps,
            matched_app=app_name,
            match_confidence=confidence
        )
        self.db.add(sighting)
    
    async def _learn_signature(
        self, 
        domain: str, 
        app_name: str, 
        store_id: str, 
        installed_apps: List[str],
        confidence: float
    ):
        """Learn a new signature from a match"""
        # Create new signature
        signature = AppSignature(
            domain=domain.lower(),
            app_name=app_name,
            confidence=confidence,
            is_from_hardcoded=False
        )
        self.db.add(signature)
        await self.db.flush()
        
        # Record sighting
        sighting = AppSignatureSighting(
            signature_id=signature.id,
            store_id=store_id,
            installed_apps=installed_apps,
            matched_app=app_name,
            match_confidence=confidence
        )
        self.db.add(sighting)
        
        print(f"🧠 [Sherlock] Learned new signature: {domain} → {app_name}")
    
    async def _record_unknown(self, domain: str, store_id: str, installed_apps: List[str]):
        """Record an unknown domain for future analysis"""
        # Check if we've seen this domain before
        result = await self.db.execute(
            select(AppSignature).where(AppSignature.domain == domain.lower())
        )
        signature = result.scalar_one_or_none()
        
        if signature:
            signature.times_seen += 1
            signature.last_seen = datetime.utcnow()
        else:
            # Create placeholder signature
            signature = AppSignature(
                domain=domain.lower(),
                app_name=f"Unknown ({domain})",
                confidence=0,
                is_from_hardcoded=False
            )
            self.db.add(signature)
            await self.db.flush()
        
        # Record sighting with installed apps (for future matching)
        sighting = AppSignatureSighting(
            signature_id=signature.id,
            store_id=store_id,
            installed_apps=installed_apps,
            matched_app=None,
            match_confidence=0
        )
        self.db.add(sighting)
    
    async def get_all_signatures(self, min_confidence: float = 0) -> List[AppSignature]:
        """Get all learned signatures"""
        result = await self.db.execute(
            select(AppSignature)
            .where(AppSignature.confidence >= min_confidence)
            .order_by(AppSignature.confidence.desc())
        )
        return list(result.scalars().all())
    
    async def get_unknown_domains(self) -> List[Dict]:
        """Get domains that haven't been identified yet"""
        result = await self.db.execute(
            select(AppSignature)
            .where(AppSignature.confidence == 0)
            .order_by(AppSignature.times_seen.desc())
        )
        signatures = result.scalars().all()
        
        unknown = []
        for sig in signatures:
            # Get installed apps from sightings
            sightings_result = await self.db.execute(
                select(AppSignatureSighting)
                .where(AppSignatureSighting.signature_id == sig.id)
            )
            sightings = sightings_result.scalars().all()
            
            # Collect all installed apps across sightings
            all_apps = set()
            for s in sightings:
                if s.installed_apps:
                    all_apps.update(s.installed_apps)
            
            unknown.append({
                "domain": sig.domain,
                "times_seen": sig.times_seen,
                "stores_seen": sig.stores_seen,
                "possible_apps": list(all_apps)
            })
        
        return unknown