"""
Sherlock - Timeline & Before/After Comparison Service
Tracks performance changes relative to app install dates
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from collections import defaultdict

from app.db.models import Store, InstalledApp, PerformanceSnapshot, Diagnosis


class TimelineService:
    """
    Service for analyzing store timeline and correlating
    performance changes with app installations
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def build_store_timeline(self, store: Store, days: int = 90) -> Dict[str, Any]:
        """
        Build a comprehensive timeline showing:
        - App installations
        - Performance snapshots
        - Correlations between the two
        
        Args:
            store: The store to analyze
            days: How many days back to look
        
        Returns:
            Timeline with events and correlations
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        # Get app installations
        apps_result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store.id)
            .where(InstalledApp.installed_on >= cutoff)
            .order_by(InstalledApp.installed_on.asc())
        )
        apps = list(apps_result.scalars().all())
        
        # Get performance snapshots
        perf_result = await self.db.execute(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.store_id == store.id)
            .where(PerformanceSnapshot.tested_at >= cutoff)
            .order_by(PerformanceSnapshot.tested_at.asc())
        )
        snapshots = list(perf_result.scalars().all())
        
        # Build unified timeline
        events = []
        
        for app in apps:
            if app.installed_on:
                events.append({
                    "type": "app_installed",
                    "timestamp": app.installed_on,
                    "data": {
                        "app_name": app.app_name,
                        "app_id": app.id,
                        "risk_score": app.risk_score,
                        "is_suspect": app.is_suspect,
                    }
                })
        
        for snapshot in snapshots:
            if snapshot.tested_at:
                events.append({
                    "type": "performance_snapshot",
                    "timestamp": snapshot.tested_at,
                    "data": {
                        "snapshot_id": snapshot.id,
                        "performance_score": snapshot.performance_score,
                        "load_time_ms": snapshot.load_time_ms,
                        "script_count": snapshot.script_count,
                    }
                })
        
        # Sort by timestamp
        events.sort(key=lambda x: x["timestamp"])
        
        # Find correlations
        correlations = await self._find_performance_correlations(apps, snapshots)
        
        return {
            "store": store.shopify_domain,
            "period_days": days,
            "total_events": len(events),
            "app_installs": len(apps),
            "performance_snapshots": len(snapshots),
            "timeline": [
                {
                    **event,
                    "timestamp": event["timestamp"].isoformat()
                }
                for event in events
            ],
            "correlations": correlations,
        }
    
    async def _find_performance_correlations(
        self,
        apps: List[InstalledApp],
        snapshots: List[PerformanceSnapshot]
    ) -> List[Dict[str, Any]]:
        """
        Find correlations between app installs and performance changes
        
        Looks for performance degradation within 7 days of app installation
        """
        correlations = []
        
        for app in apps:
            if not app.installed_on:
                continue
            
            # Find snapshots before and after this app install
            before_snapshots = [
                s for s in snapshots
                if s.tested_at and s.tested_at < app.installed_on
                and s.tested_at > app.installed_on - timedelta(days=14)
            ]
            
            after_snapshots = [
                s for s in snapshots
                if s.tested_at and s.tested_at >= app.installed_on
                and s.tested_at < app.installed_on + timedelta(days=14)
            ]
            
            if not before_snapshots or not after_snapshots:
                continue
            
            # Calculate averages
            avg_before = {
                "performance_score": sum(s.performance_score or 0 for s in before_snapshots) / len(before_snapshots),
                "load_time_ms": sum(s.load_time_ms or 0 for s in before_snapshots) / len(before_snapshots),
                "script_count": sum(s.script_count or 0 for s in before_snapshots) / len(before_snapshots),
            }
            
            avg_after = {
                "performance_score": sum(s.performance_score or 0 for s in after_snapshots) / len(after_snapshots),
                "load_time_ms": sum(s.load_time_ms or 0 for s in after_snapshots) / len(after_snapshots),
                "script_count": sum(s.script_count or 0 for s in after_snapshots) / len(after_snapshots),
            }
            
            # Calculate changes
            score_change = avg_after["performance_score"] - avg_before["performance_score"]
            load_time_change = avg_after["load_time_ms"] - avg_before["load_time_ms"]
            script_change = avg_after["script_count"] - avg_before["script_count"]
            
            # Determine if this is a significant negative impact
            is_negative_impact = (
                score_change < -5 or  # Score dropped by 5+
                load_time_change > 500 or  # Load time increased by 500ms+
                script_change > 3  # Added 3+ scripts
            )
            
            if is_negative_impact:
                correlations.append({
                    "app_name": app.app_name,
                    "app_id": app.id,
                    "installed_on": app.installed_on.isoformat(),
                    "impact": "negative",
                    "confidence": self._calculate_correlation_confidence(
                        score_change, load_time_change, script_change
                    ),
                    "changes": {
                        "performance_score": {
                            "before": round(avg_before["performance_score"], 1),
                            "after": round(avg_after["performance_score"], 1),
                            "change": round(score_change, 1),
                        },
                        "load_time_ms": {
                            "before": round(avg_before["load_time_ms"]),
                            "after": round(avg_after["load_time_ms"]),
                            "change": round(load_time_change),
                        },
                        "script_count": {
                            "before": round(avg_before["script_count"]),
                            "after": round(avg_after["script_count"]),
                            "change": round(script_change),
                        },
                    },
                    "verdict": self._generate_verdict(score_change, load_time_change),
                })
        
        # Sort by confidence
        correlations.sort(key=lambda x: x["confidence"], reverse=True)
        
        return correlations
    
    def _calculate_correlation_confidence(
        self,
        score_change: float,
        load_time_change: float,
        script_change: float
    ) -> float:
        """Calculate confidence in the correlation"""
        confidence = 50.0  # Base
        
        # Score change impact
        if score_change < -20:
            confidence += 25
        elif score_change < -10:
            confidence += 15
        elif score_change < -5:
            confidence += 10
        
        # Load time impact
        if load_time_change > 2000:
            confidence += 20
        elif load_time_change > 1000:
            confidence += 15
        elif load_time_change > 500:
            confidence += 10
        
        # Script count impact
        if script_change > 5:
            confidence += 10
        elif script_change > 3:
            confidence += 5
        
        return min(confidence, 95.0)
    
    def _generate_verdict(self, score_change: float, load_time_change: float) -> str:
        """Generate human-readable verdict"""
        if score_change < -15 or load_time_change > 1500:
            return "HIGHLY LIKELY CAUSE - This app significantly degraded performance"
        elif score_change < -10 or load_time_change > 1000:
            return "LIKELY CAUSE - Performance dropped noticeably after this install"
        elif score_change < -5 or load_time_change > 500:
            return "POSSIBLE CAUSE - Some performance impact detected"
        else:
            return "MINOR IMPACT - Small changes detected"
    
    async def compare_before_after(
        self,
        store: Store,
        app_id: str
    ) -> Dict[str, Any]:
        """
        Detailed before/after comparison for a specific app
        
        Args:
            store: The store
            app_id: ID of the app to analyze
        
        Returns:
            Detailed comparison data
        """
        # Get the app
        result = await self.db.execute(
            select(InstalledApp).where(InstalledApp.id == app_id)
        )
        app = result.scalar_one_or_none()
        
        if not app or not app.installed_on:
            return {"error": "App not found or no install date"}
        
        # Get snapshots 14 days before and after
        before_start = app.installed_on - timedelta(days=14)
        after_end = app.installed_on + timedelta(days=14)
        
        perf_result = await self.db.execute(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.store_id == store.id)
            .where(PerformanceSnapshot.tested_at >= before_start)
            .where(PerformanceSnapshot.tested_at <= after_end)
            .order_by(PerformanceSnapshot.tested_at.asc())
        )
        snapshots = list(perf_result.scalars().all())
        
        before = [s for s in snapshots if s.tested_at < app.installed_on]
        after = [s for s in snapshots if s.tested_at >= app.installed_on]
        
        return {
            "app": {
                "name": app.app_name,
                "id": app.id,
                "installed_on": app.installed_on.isoformat(),
                "risk_score": app.risk_score,
            },
            "before": {
                "snapshot_count": len(before),
                "avg_performance_score": (
                    sum(s.performance_score or 0 for s in before) / len(before)
                    if before else None
                ),
                "avg_load_time_ms": (
                    sum(s.load_time_ms or 0 for s in before) / len(before)
                    if before else None
                ),
                "snapshots": [
                    {
                        "tested_at": s.tested_at.isoformat(),
                        "performance_score": s.performance_score,
                        "load_time_ms": s.load_time_ms,
                    }
                    for s in before
                ],
            },
            "after": {
                "snapshot_count": len(after),
                "avg_performance_score": (
                    sum(s.performance_score or 0 for s in after) / len(after)
                    if after else None
                ),
                "avg_load_time_ms": (
                    sum(s.load_time_ms or 0 for s in after) / len(after)
                    if after else None
                ),
                "snapshots": [
                    {
                        "tested_at": s.tested_at.isoformat(),
                        "performance_score": s.performance_score,
                        "load_time_ms": s.load_time_ms,
                    }
                    for s in after
                ],
            },
            "has_enough_data": len(before) >= 1 and len(after) >= 1,
        }
    
    async def get_performance_impact_ranking(self, store: Store) -> List[Dict[str, Any]]:
        """
        Rank all apps by their estimated performance impact
        
        Returns apps sorted by negative impact
        """
        # Get all apps with install dates
        apps_result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store.id)
            .where(InstalledApp.installed_on.isnot(None))
        )
        apps = list(apps_result.scalars().all())
        
        # Get all performance snapshots
        perf_result = await self.db.execute(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.store_id == store.id)
            .order_by(PerformanceSnapshot.tested_at.asc())
        )
        snapshots = list(perf_result.scalars().all())
        
        if not snapshots:
            return []
        
        rankings = []
        
        for app in apps:
            if not app.installed_on:
                continue
            
            # Find the closest snapshots before and after
            before = [s for s in snapshots if s.tested_at and s.tested_at < app.installed_on]
            after = [s for s in snapshots if s.tested_at and s.tested_at >= app.installed_on]
            
            if before and after:
                # Use closest snapshot before and first snapshot after
                closest_before = before[-1]
                closest_after = after[0]
                
                score_before = closest_before.performance_score or 50
                score_after = closest_after.performance_score or 50
                
                load_before = closest_before.load_time_ms or 2000
                load_after = closest_after.load_time_ms or 2000
                
                score_impact = score_after - score_before
                load_impact = load_after - load_before
                
                # Calculate overall impact score (negative = bad)
                impact_score = score_impact - (load_impact / 100)  # Normalize load time
                
                rankings.append({
                    "app_name": app.app_name,
                    "app_id": app.id,
                    "installed_on": app.installed_on.isoformat(),
                    "impact_score": round(impact_score, 1),
                    "performance_change": round(score_impact, 1),
                    "load_time_change_ms": round(load_impact),
                    "risk_score": app.risk_score,
                    "is_negative_impact": impact_score < -5,
                })
        
        # Sort by impact (most negative first)
        rankings.sort(key=lambda x: x["impact_score"])
        
        return rankings
    
    async def suggest_removal_order(self, store: Store) -> List[Dict[str, Any]]:
        """
        Suggest which apps to try removing first based on:
        1. Performance impact
        2. Risk score
        3. Install recency
        
        Returns ordered list of apps to try uninstalling
        """
        # Get impact rankings
        impact_rankings = await self.get_performance_impact_ranking(store)
        
        # Get all suspect apps
        apps_result = await self.db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store.id)
            .where(InstalledApp.is_suspect == True)
            .order_by(InstalledApp.risk_score.desc())
        )
        suspect_apps = list(apps_result.scalars().all())
        
        suggestions = []
        seen_apps = set()
        
        # Priority 1: Apps with measured negative impact
        for ranking in impact_rankings:
            if ranking["is_negative_impact"] and ranking["app_id"] not in seen_apps:
                suggestions.append({
                    "priority": 1,
                    "app_name": ranking["app_name"],
                    "app_id": ranking["app_id"],
                    "reason": f"Measured negative impact: {ranking['performance_change']:.0f} point score drop, +{ranking['load_time_change_ms']}ms load time",
                    "confidence": "HIGH - Based on actual performance data",
                })
                seen_apps.add(ranking["app_id"])
        
        # Priority 2: High risk suspect apps (not already in list)
        for app in suspect_apps:
            if app.id not in seen_apps and app.risk_score >= 50:
                suggestions.append({
                    "priority": 2,
                    "app_name": app.app_name,
                    "app_id": app.id,
                    "reason": f"High risk score ({app.risk_score:.0f}) - {(app.risk_reasons or ['Known problematic app'])[0]}",
                    "confidence": "MEDIUM - Based on risk analysis",
                })
                seen_apps.add(app.id)
        
        # Priority 3: Recently installed suspect apps
        for app in suspect_apps:
            if app.id not in seen_apps:
                installed_days = None
                if app.installed_on:
                    installed_days = (datetime.utcnow() - app.installed_on).days
                
                suggestions.append({
                    "priority": 3,
                    "app_name": app.app_name,
                    "app_id": app.id,
                    "reason": f"Suspect app" + (f" installed {installed_days} days ago" if installed_days else ""),
                    "confidence": "MEDIUM - Based on risk analysis",
                })
                seen_apps.add(app.id)
        
        # Limit to top 10
        return suggestions[:10]
