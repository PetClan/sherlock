"""
Sherlock - WordPress API Router
All /api/v1/wp/ endpoints for the WordPress plugin to communicate with.

Endpoints:
    POST /sites/register         - Register a new WordPress site
    POST /license/validate       - Validate license key
    GET  /plugins/{slug}/intel   - Full plugin intelligence
    GET  /plugins/{slug}/reddit  - Reddit reputation data
    GET  /plugins/{slug}/search  - Google search intelligence
    POST /scans/submit           - Submit scan results for learning
    GET  /signatures/wordpress   - Get known plugin signatures
    POST /events/plugin          - Report a plugin event
    GET  /sites/{site_id}/stats  - Get site scan statistics
"""

from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.database import get_db
from app.db.wp_models import WordPressSite, WPScanSubmission, WPPluginEvent
from app.services.wp_intel_service import WPIntelService


router = APIRouter(prefix="/wp", tags=["WordPress"])


# ==================== Pydantic Models ====================

class SiteRegistration(BaseModel):
    site_url: str
    site_name: Optional[str] = None
    wp_version: Optional[str] = None
    php_version: Optional[str] = None
    active_theme: Optional[str] = None
    active_plugins_count: int = 0
    platform: str = "wordpress"


class LicenseValidation(BaseModel):
    license_key: str
    site_url: str
    platform: str = "wordpress"


class ScanSubmission(BaseModel):
    scan_type: str  # theme_monitor, plugin_conflict, css_risk
    scan_source: str = "automated"
    issues_found: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    results: Optional[List[Dict[str, Any]]] = None
    active_plugins: Optional[List[str]] = None
    active_theme: Optional[str] = None


class PluginEventReport(BaseModel):
    plugin_slug: str
    plugin_name: Optional[str] = None
    plugin_version: Optional[str] = None
    event_type: str  # activated, deactivated, updated, theme_switched
    event_details: Optional[Dict[str, Any]] = None


# ==================== Auth Dependency ====================

async def get_wp_site(
    x_sherlock_api_key: Optional[str] = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db)
) -> Optional[WordPressSite]:
    """
    Authenticate WordPress site by API key from Authorization header.
    Returns the site if found, None for unauthenticated endpoints.
    """
    if not x_sherlock_api_key:
        return None

    # Strip "Bearer " prefix if present
    api_key = x_sherlock_api_key
    if api_key.startswith("Bearer "):
        api_key = api_key[7:]

    result = await db.execute(
        select(WordPressSite).where(
            WordPressSite.api_key == api_key,
            WordPressSite.is_active == True
        )
    )
    site = result.scalar_one_or_none()

    if site:
        # Update last checkin
        site.last_checkin_at = datetime.utcnow()
        await db.flush()

    return site


async def require_wp_site(
    site: Optional[WordPressSite] = Depends(get_wp_site),
) -> WordPressSite:
    """Require authenticated WordPress site"""
    if not site:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include your Sherlock API key in the Authorization header."
        )
    return site


# ==================== Public Endpoints (No Auth Required) ====================

@router.post("/sites/register")
async def register_site(
    data: SiteRegistration,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new WordPress site with Sherlock.
    Returns an API key for subsequent authenticated requests.
    """
    try:
        intel_service = WPIntelService(db)
        result = await intel_service.register_site(data.model_dump())
        return result
    except Exception as e:
        print(f"❌ [WP] Site registration error: {e}")
        raise HTTPException(status_code=500, detail="Failed to register site")


@router.post("/license/validate")
async def validate_license(
    data: LicenseValidation,
    db: AsyncSession = Depends(get_db)
):
    """
    Validate a license key for a WordPress site.
    Returns plan information and validity status.
    """
    try:
        intel_service = WPIntelService(db)
        result = await intel_service.validate_license(data.license_key, data.site_url)
        return result
    except Exception as e:
        print(f"❌ [WP] License validation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate license")


# ==================== Plugin Intelligence (No Auth Required) ====================

@router.get("/plugins/{plugin_slug}/intel")
async def get_plugin_intel(
    plugin_slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive intelligence for a WordPress plugin.
    Combines Reddit, Google Search, and Sherlock's learned signatures.
    """
    try:
        intel_service = WPIntelService(db)
        result = await intel_service.get_plugin_intel(plugin_slug)
        return result
    except Exception as e:
        print(f"❌ [WP] Plugin intel error for {plugin_slug}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get plugin intelligence")


@router.get("/plugins/{plugin_slug}/reddit")
async def get_plugin_reddit(
    plugin_slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get Reddit reputation data for a WordPress plugin.
    Searches r/wordpress, r/WordpressPlugins, and r/webdev.
    """
    try:
        intel_service = WPIntelService(db)
        result = await intel_service.get_plugin_reddit_data(plugin_slug)
        return result
    except Exception as e:
        print(f"❌ [WP] Reddit intel error for {plugin_slug}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get Reddit data")


@router.get("/plugins/{plugin_slug}/search")
async def get_plugin_search(
    plugin_slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get Google Search intelligence for a WordPress plugin.
    Searches for reviews, complaints, and conflict reports.
    """
    try:
        intel_service = WPIntelService(db)
        result = await intel_service.get_plugin_search_data(plugin_slug)
        return result
    except Exception as e:
        print(f"❌ [WP] Search intel error for {plugin_slug}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get search data")


# ==================== Signatures (No Auth Required) ====================

@router.get("/signatures/wordpress")
async def get_wordpress_signatures(
    db: AsyncSession = Depends(get_db)
):
    """
    Get known WordPress plugin signatures.
    The PHP plugin uses these to identify patterns without
    needing to call the backend for every scan.
    """
    try:
        intel_service = WPIntelService(db)
        signatures = await intel_service.get_known_signatures()
        return {
            "platform": "wordpress",
            "signatures_count": len(signatures),
            "signatures": signatures,
            "updated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"❌ [WP] Get signatures error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get signatures")


# ==================== Authenticated Endpoints ====================

@router.post("/scans/submit")
async def submit_scan_data(
    data: ScanSubmission,
    site: WordPressSite = Depends(require_wp_site),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit scan results from a WordPress plugin instance.
    Sherlock learns from these to improve its signature database.
    Requires API key authentication.
    """
    try:
        intel_service = WPIntelService(db)
        result = await intel_service.process_scan_submission(
            site_id=site.id,
            scan_data=data.model_dump()
        )
        return result
    except Exception as e:
        print(f"❌ [WP] Scan submission error for {site.site_url}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process scan data")


@router.post("/events/plugin")
async def report_plugin_event(
    data: PluginEventReport,
    site: WordPressSite = Depends(require_wp_site),
    db: AsyncSession = Depends(get_db)
):
    """
    Report a plugin event (activation, deactivation, update, theme switch).
    Helps Sherlock correlate plugin changes with theme issues.
    Requires API key authentication.
    """
    try:
        event = WPPluginEvent(
            site_id=site.id,
            plugin_slug=data.plugin_slug,
            plugin_name=data.plugin_name,
            plugin_version=data.plugin_version,
            event_type=data.event_type,
            event_details=data.event_details,
        )
        db.add(event)
        await db.flush()

        return {
            "status": "recorded",
            "event_id": event.id,
            "message": f"Plugin event '{data.event_type}' recorded for {data.plugin_slug}",
        }
    except Exception as e:
        print(f"❌ [WP] Plugin event error for {site.site_url}: {e}")
        raise HTTPException(status_code=500, detail="Failed to record plugin event")


@router.get("/sites/me")
async def get_my_site(
    site: WordPressSite = Depends(require_wp_site),
):
    """
    Get the authenticated site's information.
    The PHP plugin uses this to verify connectivity and get plan info.
    """
    return {
        "site_id": site.id,
        "site_url": site.site_url,
        "site_name": site.site_name,
        "plan": site.plan,
        "plan_expires_at": site.plan_expires_at.isoformat() if site.plan_expires_at else None,
        "registered_at": site.registered_at.isoformat() if site.registered_at else None,
        "is_active": site.is_active,
    }


@router.get("/sites/me/stats")
async def get_my_site_stats(
    site: WordPressSite = Depends(require_wp_site),
    db: AsyncSession = Depends(get_db)
):
    """
    Get scan statistics for the authenticated site.
    """
    try:
        # Total scans
        total_scans = await db.scalar(
            select(func.count(WPScanSubmission.id))
            .where(WPScanSubmission.site_id == site.id)
        )

        # Scans by type
        scan_types = await db.execute(
            select(
                WPScanSubmission.scan_type,
                func.count(WPScanSubmission.id).label("count")
            )
            .where(WPScanSubmission.site_id == site.id)
            .group_by(WPScanSubmission.scan_type)
        )
        type_counts = {row[0]: row[1] for row in scan_types}

        # Total issues found
        total_issues = await db.scalar(
            select(func.sum(WPScanSubmission.issues_found))
            .where(WPScanSubmission.site_id == site.id)
        ) or 0

        # Total critical issues
        total_critical = await db.scalar(
            select(func.sum(WPScanSubmission.critical_count))
            .where(WPScanSubmission.site_id == site.id)
        ) or 0

        # Last scan
        last_scan = await db.scalar(
            select(func.max(WPScanSubmission.scanned_at))
            .where(WPScanSubmission.site_id == site.id)
        )

        # Plugin events count
        total_events = await db.scalar(
            select(func.count(WPPluginEvent.id))
            .where(WPPluginEvent.site_id == site.id)
        )

        return {
            "site_id": site.id,
            "total_scans": total_scans,
            "scans_by_type": type_counts,
            "total_issues_found": total_issues,
            "total_critical_issues": total_critical,
            "total_plugin_events": total_events,
            "last_scan_at": last_scan.isoformat() if last_scan else None,
        }

    except Exception as e:
        print(f"❌ [WP] Stats error for {site.site_url}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get site stats")


# ==================== Health Check ====================

@router.get("/health")
async def wp_health_check():
    """Health check endpoint for the WordPress API"""
    return {
        "status": "healthy",
        "platform": "wordpress",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }
