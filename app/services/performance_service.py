"""
Sherlock - Performance Service
Measures store performance, identifies slow resources and blocking scripts
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
import re
import time
from urllib.parse import urlparse

from app.db.models import Store, PerformanceSnapshot


# Known slow/heavy third-party domains
HEAVY_THIRD_PARTY_DOMAINS = {
    "pagefly": {"weight": "heavy", "typical_impact_ms": 800},
    "gempages": {"weight": "heavy", "typical_impact_ms": 700},
    "shogun": {"weight": "heavy", "typical_impact_ms": 600},
    "loox": {"weight": "medium", "typical_impact_ms": 300},
    "judge.me": {"weight": "light", "typical_impact_ms": 150},
    "klaviyo": {"weight": "medium", "typical_impact_ms": 250},
    "privy": {"weight": "medium", "typical_impact_ms": 400},
    "justuno": {"weight": "heavy", "typical_impact_ms": 500},
    "facebook": {"weight": "medium", "typical_impact_ms": 200},
    "google-analytics": {"weight": "light", "typical_impact_ms": 100},
    "googletagmanager": {"weight": "medium", "typical_impact_ms": 200},
    "hotjar": {"weight": "medium", "typical_impact_ms": 300},
    "tidio": {"weight": "medium", "typical_impact_ms": 350},
    "intercom": {"weight": "heavy", "typical_impact_ms": 450},
    "drift": {"weight": "heavy", "typical_impact_ms": 400},
    "zendesk": {"weight": "medium", "typical_impact_ms": 300},
    "gorgias": {"weight": "medium", "typical_impact_ms": 250},
    "yotpo": {"weight": "medium", "typical_impact_ms": 350},
    "stamped": {"weight": "light", "typical_impact_ms": 200},
    "omnisend": {"weight": "medium", "typical_impact_ms": 250},
    "mailchimp": {"weight": "light", "typical_impact_ms": 150},
    "afterpay": {"weight": "light", "typical_impact_ms": 150},
    "klarna": {"weight": "medium", "typical_impact_ms": 200},
    "recharge": {"weight": "medium", "typical_impact_ms": 300},
}

# Performance thresholds (in milliseconds)
PERFORMANCE_THRESHOLDS = {
    "load_time": {
        "good": 2000,
        "moderate": 4000,
        "poor": 6000
    },
    "ttfb": {  # Time to First Byte
        "good": 200,
        "moderate": 500,
        "poor": 1000
    },
    "tti": {  # Time to Interactive
        "good": 3000,
        "moderate": 5000,
        "poor": 8000
    }
}


class PerformanceService:
    """Service for measuring and analyzing store performance"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def measure_page_performance(
        self, 
        store: Store, 
        page: str = "homepage"
    ) -> Dict[str, Any]:
        """
        Measure basic performance metrics for a store page
        
        Pages: homepage, product, collection, cart
        """
        print(f"⏱️ [Performance] Measuring {page} for {store.shopify_domain}")
        
        # Construct URL
        base_url = f"https://{store.shopify_domain}"
        
        page_urls = {
            "homepage": base_url,
            "product": f"{base_url}/products",  # Will redirect to a product or 404
            "collection": f"{base_url}/collections/all",
            "cart": f"{base_url}/cart",
        }
        
        url = page_urls.get(page, base_url)
        
        metrics = {
            "url": url,
            "page": page,
            "measured_at": datetime.utcnow().isoformat(),
        }
        
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                # Measure Time to First Byte (TTFB)
                start_time = time.time()
                
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; Sherlock/1.0; Shopify App Diagnostics)",
                        "Accept": "text/html,application/xhtml+xml",
                    },
                    timeout=30.0
                )
                
                ttfb = int((time.time() - start_time) * 1000)
                
                # Get full response for analysis
                content = response.text
                total_time = int((time.time() - start_time) * 1000)
                
                # Analyze the HTML
                analysis = await self._analyze_page_content(content)
                
                metrics.update({
                    "status_code": response.status_code,
                    "ttfb_ms": ttfb,
                    "load_time_ms": total_time,
                    "content_size_kb": len(content) / 1024,
                    **analysis
                })
                
                # Calculate performance score
                metrics["performance_score"] = self._calculate_score(metrics)
                
        except httpx.TimeoutException:
            metrics.update({
                "error": "Request timed out after 30 seconds",
                "load_time_ms": 30000,
                "performance_score": 0
            })
        except Exception as e:
            metrics.update({
                "error": str(e),
                "performance_score": 0
            })
        
        return metrics
    
    async def _analyze_page_content(self, html: str) -> Dict[str, Any]:
        """Analyze HTML content for performance indicators"""
        analysis = {
            "script_count": 0,
            "third_party_script_count": 0,
            "inline_script_count": 0,
            "stylesheet_count": 0,
            "image_count": 0,
            "third_party_domains": [],
            "blocking_scripts": [],
            "slow_resources": [],
            "estimated_impact_ms": 0,
        }
        
        # Count scripts
        external_scripts = re.findall(
            r'<script[^>]*src=["\']([^"\']+)["\']', 
            html, 
            re.IGNORECASE
        )
        inline_scripts = re.findall(
            r'<script[^>]*>.*?</script>', 
            html, 
            re.DOTALL | re.IGNORECASE
        )
        
        analysis["script_count"] = len(external_scripts) + len(inline_scripts)
        analysis["inline_script_count"] = len(inline_scripts)
        
        # Analyze external scripts
        third_party_domains = set()
        blocking_scripts = []
        estimated_impact = 0
        
        for src in external_scripts:
            domain = self._extract_domain(src)
            is_shopify = "shopify" in domain or "myshopify" in domain
            
            if not is_shopify:
                third_party_domains.add(domain)
                
                # Check if it's a known heavy domain
                for known_domain, info in HEAVY_THIRD_PARTY_DOMAINS.items():
                    if known_domain in domain.lower() or known_domain in src.lower():
                        estimated_impact += info["typical_impact_ms"]
                        
                        if info["weight"] == "heavy":
                            blocking_scripts.append({
                                "src": src[:100],
                                "domain": domain,
                                "estimated_impact_ms": info["typical_impact_ms"]
                            })
                        break
        
        analysis["third_party_script_count"] = len(third_party_domains)
        analysis["third_party_domains"] = list(third_party_domains)
        analysis["blocking_scripts"] = blocking_scripts
        analysis["estimated_impact_ms"] = estimated_impact
        
        # Count stylesheets
        stylesheets = re.findall(
            r'<link[^>]*rel=["\']stylesheet["\']', 
            html, 
            re.IGNORECASE
        )
        analysis["stylesheet_count"] = len(stylesheets)
        
        # Count images
        images = re.findall(r'<img[^>]*>', html, re.IGNORECASE)
        analysis["image_count"] = len(images)
        
        # Identify slow resources
        if analysis["script_count"] > 20:
            analysis["slow_resources"].append({
                "type": "excessive_scripts",
                "count": analysis["script_count"],
                "recommendation": "Reduce number of scripts - consider consolidating apps"
            })
        
        if analysis["third_party_script_count"] > 10:
            analysis["slow_resources"].append({
                "type": "excessive_third_party",
                "count": analysis["third_party_script_count"],
                "recommendation": "Too many third-party scripts - review installed apps"
            })
        
        return analysis
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            parsed = urlparse(url)
            return parsed.netloc or url.split("/")[0]
        except:
            return url
    
    def _calculate_score(self, metrics: Dict[str, Any]) -> float:
        """
        Calculate overall performance score (0-100)
        Based on load time, TTFB, script count, third-party impact
        """
        score = 100.0
        
        # Penalize for slow load time
        load_time = metrics.get("load_time_ms", 0)
        if load_time > PERFORMANCE_THRESHOLDS["load_time"]["poor"]:
            score -= 40
        elif load_time > PERFORMANCE_THRESHOLDS["load_time"]["moderate"]:
            score -= 25
        elif load_time > PERFORMANCE_THRESHOLDS["load_time"]["good"]:
            score -= 10
        
        # Penalize for slow TTFB
        ttfb = metrics.get("ttfb_ms", 0)
        if ttfb > PERFORMANCE_THRESHOLDS["ttfb"]["poor"]:
            score -= 20
        elif ttfb > PERFORMANCE_THRESHOLDS["ttfb"]["moderate"]:
            score -= 10
        elif ttfb > PERFORMANCE_THRESHOLDS["ttfb"]["good"]:
            score -= 5
        
        # Penalize for excessive scripts
        script_count = metrics.get("script_count", 0)
        if script_count > 30:
            score -= 20
        elif script_count > 20:
            score -= 10
        elif script_count > 15:
            score -= 5
        
        # Penalize for third-party scripts
        third_party = metrics.get("third_party_script_count", 0)
        if third_party > 15:
            score -= 15
        elif third_party > 10:
            score -= 10
        elif third_party > 5:
            score -= 5
        
        # Penalize for blocking scripts
        blocking = len(metrics.get("blocking_scripts", []))
        score -= blocking * 5
        
        return max(0, min(100, score))
    
    async def run_full_performance_audit(self, store: Store) -> Dict[str, Any]:
        """
        Run complete performance audit:
        1. Test homepage
        2. Test a product page
        3. Test collection page
        4. Identify worst offenders
        5. Store snapshot
        """
        print(f"🔍 [Performance] Running full audit for {store.shopify_domain}")
        
        pages_to_test = ["homepage", "collection", "cart"]
        results = {}
        
        for page in pages_to_test:
            results[page] = await self.measure_page_performance(store, page)
            # Small delay between requests
            await self._delay(500)
        
        # Calculate aggregate metrics
        avg_load_time = sum(
            r.get("load_time_ms", 0) for r in results.values()
        ) / len(results)
        
        avg_score = sum(
            r.get("performance_score", 0) for r in results.values()
        ) / len(results)
        
        # Collect all third-party domains
        all_domains = set()
        all_blocking = []
        
        for page_result in results.values():
            all_domains.update(page_result.get("third_party_domains", []))
            all_blocking.extend(page_result.get("blocking_scripts", []))
        
        # Store snapshot (using homepage as primary)
        homepage = results.get("homepage", {})
        
        snapshot = PerformanceSnapshot(
            store_id=store.id,
            load_time_ms=homepage.get("load_time_ms"),
            time_to_first_byte_ms=homepage.get("ttfb_ms"),
            performance_score=avg_score,
            total_requests=homepage.get("script_count", 0) + homepage.get("stylesheet_count", 0),
            total_size_kb=homepage.get("content_size_kb"),
            script_count=homepage.get("script_count"),
            third_party_script_count=homepage.get("third_party_script_count"),
            slow_resources=homepage.get("slow_resources"),
            blocking_scripts=all_blocking,
            page_tested="homepage"
        )
        
        self.db.add(snapshot)
        await self.db.flush()
        
        # Generate recommendations
        recommendations = self._generate_recommendations(results, all_blocking)
        
        print(f"✅ [Performance] Audit complete. Score: {avg_score:.0f}/100")
        
        return {
            "success": True,
            "snapshot_id": snapshot.id,
            "average_load_time_ms": int(avg_load_time),
            "average_score": round(avg_score, 1),
            "pages_tested": len(results),
            "third_party_domains": list(all_domains),
            "blocking_scripts": all_blocking,
            "recommendations": recommendations,
            "details": results
        }
    
    def _generate_recommendations(
        self, 
        results: Dict[str, Dict], 
        blocking_scripts: List[Dict]
    ) -> List[Dict[str, Any]]:
        """Generate actionable performance recommendations"""
        recommendations = []
        
        # Check for heavy blocking scripts
        if blocking_scripts:
            # Group by domain
            domains = {}
            for script in blocking_scripts:
                domain = script.get("domain", "Unknown")
                if domain not in domains:
                    domains[domain] = 0
                domains[domain] += script.get("estimated_impact_ms", 0)
            
            # Sort by impact
            sorted_domains = sorted(domains.items(), key=lambda x: x[1], reverse=True)
            
            for domain, impact in sorted_domains[:3]:  # Top 3
                recommendations.append({
                    "priority": "high",
                    "type": "blocking_script",
                    "domain": domain,
                    "estimated_impact_ms": impact,
                    "action": f"Consider removing or deferring scripts from {domain}",
                    "potential_improvement": f"Could save ~{impact}ms"
                })
        
        # Check for slow pages
        for page, metrics in results.items():
            load_time = metrics.get("load_time_ms", 0)
            
            if load_time > 5000:
                recommendations.append({
                    "priority": "high",
                    "type": "slow_page",
                    "page": page,
                    "load_time_ms": load_time,
                    "action": f"The {page} is critically slow ({load_time}ms). Review installed apps.",
                    "potential_improvement": "Target: under 3000ms"
                })
            elif load_time > 3000:
                recommendations.append({
                    "priority": "medium",
                    "type": "slow_page",
                    "page": page,
                    "load_time_ms": load_time,
                    "action": f"The {page} could be faster ({load_time}ms).",
                    "potential_improvement": "Target: under 2000ms"
                })
        
        # Check for excessive scripts
        homepage = results.get("homepage", {})
        script_count = homepage.get("script_count", 0)
        
        if script_count > 25:
            recommendations.append({
                "priority": "high",
                "type": "excessive_scripts",
                "count": script_count,
                "action": "Too many scripts loaded. Audit installed apps and remove unused ones.",
                "potential_improvement": "Removing 5-10 scripts could save 500-1500ms"
            })
        
        return recommendations
    
    async def _delay(self, ms: int):
        """Async delay helper"""
        import asyncio
        await asyncio.sleep(ms / 1000)
    
    async def get_performance_trend(
        self, 
        store: Store, 
        days: int = 30
    ) -> Dict[str, Any]:
        """Get performance trend over time"""
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        result = await self.db.execute(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.store_id == store.id)
            .where(PerformanceSnapshot.tested_at >= cutoff)
            .order_by(PerformanceSnapshot.tested_at.asc())
        )
        
        snapshots = list(result.scalars().all())
        
        if not snapshots:
            return {"trend": "no_data", "snapshots": []}
        
        # Calculate trend
        if len(snapshots) >= 2:
            first_score = snapshots[0].performance_score or 0
            last_score = snapshots[-1].performance_score or 0
            
            if last_score > first_score + 5:
                trend = "improving"
            elif last_score < first_score - 5:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"
        
        return {
            "trend": trend,
            "days": days,
            "snapshot_count": len(snapshots),
            "first_score": snapshots[0].performance_score if snapshots else None,
            "latest_score": snapshots[-1].performance_score if snapshots else None,
            "snapshots": [
                {
                    "tested_at": s.tested_at.isoformat(),
                    "performance_score": s.performance_score,
                    "load_time_ms": s.load_time_ms
                }
                for s in snapshots
            ]
        }
