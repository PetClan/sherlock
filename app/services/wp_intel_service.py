"""
Sherlock - WordPress Plugin Intelligence Service
Provides reputation and risk data for WordPress plugins by leveraging
the existing Reddit and Google Search services with WordPress-specific queries.
Also manages the cross-platform plugin signature learning system.
"""

import asyncio
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from uuid import uuid4

from app.services.reddit_service import RedditService
from app.services.google_search_service import GoogleSearchService
from app.db.wp_models import WPPluginSignature, WPScanSubmission, WPPluginEvent


class WPIntelService:
    """WordPress Plugin Intelligence Service"""

    # WordPress-specific subreddits and search contexts
    WP_SUBREDDITS = ["wordpress", "WordpressPlugins", "webdev", "Wordpress"]
    WP_SEARCH_CONTEXT = "wordpress plugin"

    # Cache TTL for intelligence data (1 hour)
    INTEL_CACHE_TTL = timedelta(hours=1)

    def __init__(self, db: AsyncSession):
        self.db = db
        self.reddit_service = RedditService()
        self.google_service = GoogleSearchService()

    async def get_plugin_intel(self, plugin_slug: str) -> Dict[str, Any]:
        """
        Get comprehensive intelligence for a WordPress plugin.
        Combines Reddit data, Google search data, WordPress.org API data,
        and learned signature data from our own database.
        """
        # Check if we have recent cached intel in our signatures table
        cached = await self._get_cached_intel(plugin_slug)
        if cached:
            return cached

        # Gather intel from all sources in parallel
        reddit_task = self._get_reddit_intel(plugin_slug)
        google_task = self._get_google_intel(plugin_slug)
        signature_task = self._get_signature_data(plugin_slug)

        reddit_data, google_data, signature_data = await asyncio.gather(
            reddit_task, google_task, signature_task,
            return_exceptions=True
        )

        # Handle exceptions gracefully
        if isinstance(reddit_data, Exception):
            reddit_data = {"error": str(reddit_data), "available": False}
        if isinstance(google_data, Exception):
            google_data = {"error": str(google_data), "available": False}
        if isinstance(signature_data, Exception):
            signature_data = None

        # Calculate combined risk score
        risk_score = self._calculate_risk_score(reddit_data, google_data, signature_data)

        intel = {
            "plugin_slug": plugin_slug,
            "risk_score": risk_score,
            "risk_level": self._risk_level(risk_score),
            "reddit": reddit_data,
            "search": google_data,
            "signature": signature_data,
            "fetched_at": datetime.utcnow().isoformat(),
        }

        # Update cached intel in signatures table
        await self._cache_intel(plugin_slug, reddit_data, google_data, risk_score)

        return intel

    async def get_plugin_reddit_data(self, plugin_slug: str) -> Dict[str, Any]:
        """Get Reddit reputation data for a WordPress plugin"""
        return await self._get_reddit_intel(plugin_slug)

    async def get_plugin_search_data(self, plugin_slug: str) -> Dict[str, Any]:
        """Get Google search intelligence for a WordPress plugin"""
        return await self._get_google_intel(plugin_slug)

    async def get_known_signatures(self) -> List[Dict[str, Any]]:
        """Get all known WordPress plugin signatures for the PHP plugin to use"""
        result = await self.db.execute(
            select(WPPluginSignature)
            .where(WPPluginSignature.sites_seen >= 2)  # Only return patterns seen on 2+ sites
            .order_by(WPPluginSignature.conflict_frequency.desc())
        )
        signatures = result.scalars().all()

        return [
            {
                "plugin_slug": sig.plugin_slug,
                "plugin_name": sig.plugin_name,
                "known_css_patterns": sig.known_css_patterns or [],
                "known_script_domains": sig.known_script_domains or [],
                "known_theme_modifications": sig.known_theme_modifications or [],
                "avg_risk_score": sig.avg_risk_score,
                "conflict_frequency": sig.conflict_frequency,
                "times_reported": sig.times_reported,
                "sites_seen": sig.sites_seen,
            }
            for sig in signatures
        ]

    async def process_scan_submission(self, site_id: str, scan_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process scan results submitted from a WordPress plugin instance.
        Learns from the data to improve signatures.
        """
        # Store the scan submission
        submission = WPScanSubmission(
            id=str(uuid4()),
            site_id=site_id,
            scan_type=scan_data.get("scan_type", "unknown"),
            scan_source=scan_data.get("scan_source", "automated"),
            issues_found=scan_data.get("issues_found", 0),
            critical_count=scan_data.get("critical_count", 0),
            warning_count=scan_data.get("warning_count", 0),
            info_count=scan_data.get("info_count", 0),
            results=scan_data.get("results"),
            active_plugins=scan_data.get("active_plugins"),
            active_theme=scan_data.get("active_theme"),
        )
        self.db.add(submission)

        # Learn from CSS risk findings
        if scan_data.get("scan_type") == "css_risk" and scan_data.get("results"):
            await self._learn_css_patterns(scan_data["results"])

        # Learn from plugin conflict findings
        if scan_data.get("scan_type") == "plugin_conflict" and scan_data.get("results"):
            await self._learn_conflict_patterns(scan_data["results"])

        # Update plugin signature site counts
        if scan_data.get("active_plugins"):
            await self._update_plugin_sightings(scan_data["active_plugins"])

        await self.db.flush()

        return {
            "status": "accepted",
            "submission_id": submission.id,
            "message": "Scan data received and processed",
        }

    async def validate_license(self, license_key: str, site_url: str) -> Dict[str, Any]:
        """Validate a license key and return plan information"""
        from app.db.wp_models import WordPressSite

        # Find site by URL
        result = await self.db.execute(
            select(WordPressSite).where(WordPressSite.site_url == site_url)
        )
        site = result.scalar_one_or_none()

        if not site:
            return {
                "valid": False,
                "message": "Site not registered",
                "plan": "free",
            }

        if site.license_key != license_key:
            return {
                "valid": False,
                "message": "Invalid license key",
                "plan": "free",
            }

        # Check expiration
        if site.plan_expires_at and site.plan_expires_at < datetime.utcnow():
            return {
                "valid": False,
                "message": "License expired",
                "plan": "free",
                "expired_at": site.plan_expires_at.isoformat(),
            }

        return {
            "valid": True,
            "plan": site.plan,
            "expires_at": site.plan_expires_at.isoformat() if site.plan_expires_at else None,
            "message": "License valid",
        }

    async def register_site(self, site_data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new WordPress site or update an existing one"""
        from app.db.wp_models import WordPressSite

        site_url = site_data.get("site_url", "").rstrip("/")

        # Check if site already exists
        result = await self.db.execute(
            select(WordPressSite).where(WordPressSite.site_url == site_url)
        )
        site = result.scalar_one_or_none()

        if site:
            # Update existing site
            site.wp_version = site_data.get("wp_version", site.wp_version)
            site.php_version = site_data.get("php_version", site.php_version)
            site.active_theme = site_data.get("active_theme", site.active_theme)
            site.active_plugins_count = site_data.get("active_plugins_count", site.active_plugins_count)
            site.site_name = site_data.get("site_name", site.site_name)
            site.is_active = True
            site.last_checkin_at = datetime.utcnow()
            await self.db.flush()

            return {
                "status": "updated",
                "site_id": site.id,
                "api_key": site.api_key,
                "plan": site.plan,
                "message": "Site registration updated",
            }
        else:
            # Create new site
            import secrets
            api_key = f"shrlk_wp_{secrets.token_hex(24)}"

            new_site = WordPressSite(
                id=str(uuid4()),
                site_url=site_url,
                site_name=site_data.get("site_name"),
                api_key=api_key,
                wp_version=site_data.get("wp_version"),
                php_version=site_data.get("php_version"),
                active_theme=site_data.get("active_theme"),
                active_plugins_count=site_data.get("active_plugins_count", 0),
                plan="free",
                is_active=True,
                last_checkin_at=datetime.utcnow(),
            )
            self.db.add(new_site)
            await self.db.flush()

            return {
                "status": "registered",
                "site_id": new_site.id,
                "api_key": api_key,
                "plan": "free",
                "message": "Site registered successfully. Store your API key securely.",
            }

    # ==================== Private Helper Methods ====================

    async def _get_reddit_intel(self, plugin_slug: str) -> Dict[str, Any]:
        """Search Reddit for WordPress plugin discussions"""
        try:
            # Search with WordPress context
            plugin_name = plugin_slug.replace("-", " ").title()
            results = await self.reddit_service.search_app_issues(
                app_name=f"{plugin_name} wordpress plugin",
                limit=15,
                time_filter="year"
            )

            # Also check reputation
            reputation = await self.reddit_service.check_app_reputation(
                f"{plugin_name} wordpress"
            )

            return {
                "available": True,
                "posts_found": results.get("total_posts", 0),
                "posts": results.get("posts", [])[:5],  # Top 5 posts
                "sentiment": reputation.get("sentiment", "neutral"),
                "risk_score": reputation.get("risk_score", 0),
                "common_issues": reputation.get("common_issues", []),
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    async def _get_google_intel(self, plugin_slug: str) -> Dict[str, Any]:
        """Search Google for WordPress plugin reviews and issues"""
        try:
            plugin_name = plugin_slug.replace("-", " ").title()

            # Get combined insights
            results = await self.google_service.get_combined_app_insights(
                f"{plugin_name} wordpress plugin"
            )

            if not results.get("success"):
                return {"available": False, "error": results.get("error", "Search failed")}

            return {
                "available": True,
                "results_found": results.get("total_results", 0),
                "sentiment": results.get("overall_sentiment", "neutral"),
                "sentiment_score": results.get("sentiment_score", 0),
                "top_results": results.get("results", [])[:5],
                "common_complaints": results.get("common_issues", []),
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    async def _get_signature_data(self, plugin_slug: str) -> Optional[Dict[str, Any]]:
        """Get our learned signature data for this plugin"""
        result = await self.db.execute(
            select(WPPluginSignature).where(WPPluginSignature.plugin_slug == plugin_slug)
        )
        sig = result.scalar_one_or_none()

        if not sig:
            return None

        return {
            "plugin_name": sig.plugin_name,
            "known_css_patterns": sig.known_css_patterns or [],
            "known_script_domains": sig.known_script_domains or [],
            "known_theme_modifications": sig.known_theme_modifications or [],
            "avg_risk_score": sig.avg_risk_score,
            "conflict_frequency": sig.conflict_frequency,
            "times_reported": sig.times_reported,
            "sites_seen": sig.sites_seen,
        }

    async def _get_cached_intel(self, plugin_slug: str) -> Optional[Dict[str, Any]]:
        """Check if we have recent cached intel"""
        result = await self.db.execute(
            select(WPPluginSignature).where(WPPluginSignature.plugin_slug == plugin_slug)
        )
        sig = result.scalar_one_or_none()

        if not sig or not sig.last_intel_update:
            return None

        # Check if cache is still fresh
        if datetime.utcnow() - sig.last_intel_update > self.INTEL_CACHE_TTL:
            return None

        # Return cached data
        return {
            "plugin_slug": plugin_slug,
            "risk_score": sig.avg_risk_score,
            "risk_level": self._risk_level(sig.avg_risk_score),
            "reddit": {
                "available": sig.reddit_sentiment is not None,
                "sentiment": sig.reddit_sentiment,
                "risk_score": sig.reddit_risk_score,
            },
            "search": {
                "available": sig.google_sentiment is not None,
                "sentiment": sig.google_sentiment,
            },
            "signature": {
                "plugin_name": sig.plugin_name,
                "known_css_patterns": sig.known_css_patterns or [],
                "known_script_domains": sig.known_script_domains or [],
                "avg_risk_score": sig.avg_risk_score,
                "conflict_frequency": sig.conflict_frequency,
                "sites_seen": sig.sites_seen,
            },
            "cached": True,
            "fetched_at": sig.last_intel_update.isoformat(),
        }

    async def _cache_intel(
        self,
        plugin_slug: str,
        reddit_data: Dict,
        google_data: Dict,
        risk_score: float
    ) -> None:
        """Cache intelligence data in the signatures table"""
        result = await self.db.execute(
            select(WPPluginSignature).where(WPPluginSignature.plugin_slug == plugin_slug)
        )
        sig = result.scalar_one_or_none()

        reddit_sentiment = reddit_data.get("sentiment") if isinstance(reddit_data, dict) else None
        reddit_risk = reddit_data.get("risk_score") if isinstance(reddit_data, dict) else None
        google_sentiment = google_data.get("sentiment") if isinstance(google_data, dict) else None

        if sig:
            sig.reddit_sentiment = reddit_sentiment
            sig.reddit_risk_score = reddit_risk
            sig.google_sentiment = google_sentiment
            sig.avg_risk_score = risk_score
            sig.last_intel_update = datetime.utcnow()
            sig.last_seen = datetime.utcnow()
        else:
            plugin_name = plugin_slug.replace("-", " ").title()
            new_sig = WPPluginSignature(
                id=str(uuid4()),
                plugin_slug=plugin_slug,
                plugin_name=plugin_name,
                avg_risk_score=risk_score,
                reddit_sentiment=reddit_sentiment,
                reddit_risk_score=reddit_risk,
                google_sentiment=google_sentiment,
                last_intel_update=datetime.utcnow(),
                sites_seen=0,
            )
            self.db.add(new_sig)

        await self.db.flush()

    async def _learn_css_patterns(self, results: List[Dict]) -> None:
        """Learn CSS patterns from scan results"""
        for finding in results:
            plugin_slug = finding.get("plugin_file", "")
            if "/" in plugin_slug:
                plugin_slug = plugin_slug.split("/")[0]

            selector = finding.get("selector")
            if not plugin_slug or not selector:
                continue

            result = await self.db.execute(
                select(WPPluginSignature).where(WPPluginSignature.plugin_slug == plugin_slug)
            )
            sig = result.scalar_one_or_none()

            if sig:
                patterns = sig.known_css_patterns or []
                if selector not in patterns:
                    patterns.append(selector)
                    sig.known_css_patterns = patterns[:50]  # Cap at 50 patterns
                    sig.last_seen = datetime.utcnow()
            else:
                new_sig = WPPluginSignature(
                    id=str(uuid4()),
                    plugin_slug=plugin_slug,
                    plugin_name=finding.get("source_plugin", plugin_slug),
                    known_css_patterns=[selector],
                    sites_seen=1,
                )
                self.db.add(new_sig)

    async def _learn_conflict_patterns(self, results: List[Dict]) -> None:
        """Learn conflict patterns from scan results"""
        for finding in results:
            plugins = finding.get("plugins", [])
            for plugin_name in plugins:
                slug = plugin_name.lower().replace(" ", "-")

                result = await self.db.execute(
                    select(WPPluginSignature).where(WPPluginSignature.plugin_slug == slug)
                )
                sig = result.scalar_one_or_none()

                if sig:
                    sig.times_reported = (sig.times_reported or 0) + 1
                    # Recalculate conflict frequency
                    if sig.sites_seen and sig.sites_seen > 0:
                        sig.conflict_frequency = sig.times_reported / sig.sites_seen
                    sig.last_seen = datetime.utcnow()

    async def _update_plugin_sightings(self, active_plugins: List[str]) -> None:
        """Update site counts for plugins"""
        for plugin_slug in active_plugins:
            # Normalize slug
            if "/" in plugin_slug:
                plugin_slug = plugin_slug.split("/")[0]

            result = await self.db.execute(
                select(WPPluginSignature).where(WPPluginSignature.plugin_slug == plugin_slug)
            )
            sig = result.scalar_one_or_none()

            if sig:
                sig.sites_seen = (sig.sites_seen or 0) + 1
                sig.last_seen = datetime.utcnow()
            else:
                new_sig = WPPluginSignature(
                    id=str(uuid4()),
                    plugin_slug=plugin_slug,
                    plugin_name=plugin_slug.replace("-", " ").title(),
                    sites_seen=1,
                )
                self.db.add(new_sig)

    def _calculate_risk_score(
        self,
        reddit_data: Dict,
        google_data: Dict,
        signature_data: Optional[Dict]
    ) -> float:
        """Calculate combined risk score from all intelligence sources"""
        score = 0.0
        weights_used = 0.0

        # Reddit contribution (weight: 30%)
        if isinstance(reddit_data, dict) and reddit_data.get("available"):
            reddit_risk = reddit_data.get("risk_score", 0)
            score += reddit_risk * 0.3
            weights_used += 0.3

        # Google contribution (weight: 25%)
        if isinstance(google_data, dict) and google_data.get("available"):
            sentiment_score = google_data.get("sentiment_score", 0)
            # Convert sentiment (-1 to 1) to risk (0 to 100)
            google_risk = max(0, (1 - sentiment_score) * 50)
            score += google_risk * 0.25
            weights_used += 0.25

        # Signature contribution (weight: 45%)
        if signature_data:
            sig_risk = signature_data.get("avg_risk_score", 0)
            conflict_freq = signature_data.get("conflict_frequency", 0) * 100
            combined_sig = (sig_risk * 0.6) + (conflict_freq * 0.4)
            score += combined_sig * 0.45
            weights_used += 0.45

        # Normalize if not all sources contributed
        if weights_used > 0:
            score = score / weights_used
        else:
            score = 25.0  # Default moderate-low risk for unknown plugins

        return min(100.0, max(0.0, round(score, 1)))

    @staticmethod
    def _risk_level(score: float) -> str:
        """Convert numeric score to risk level string"""
        if score >= 70:
            return "high"
        elif score >= 40:
            return "medium"
        else:
            return "low"
