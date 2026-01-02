"""
Sherlock - Shopify App Diagnostics
Main application entry point
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from typing import Optional, List
from datetime import datetime
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.db.database import init_db, get_db
from app.db.models import Store, InstalledApp, Diagnosis, ThemeIssue, PerformanceSnapshot, DailyScan
from app.services.diagnosis_service import DiagnosisService
from app.services.app_scanner_service import AppScannerService
from app.services.theme_analyzer_service import ThemeAnalyzerService
from app.services.performance_service import PerformanceService
from app.api import api_router


# Global scheduler instance
scheduler = AsyncIOScheduler()


async def run_scheduled_daily_scans():
    """
    Run daily scans for stores where local time is 1-6 AM
    Triggered every 15 minutes, filters by timezone and scan_slot
    """
    from app.db.database import async_session
    from app.services.daily_scan_service import DailyScanService
    from app.services.system_settings_service import SystemSettingsService
    from zoneinfo import ZoneInfo
    
    PARALLEL_BATCH_SIZE = 10
    SCAN_TIMEOUT_MINUTES = 10
    SCAN_WINDOW_START = 1  # 1 AM local
    SCAN_WINDOW_END = 6    # 6 AM local
    
    now_utc = datetime.utcnow()
    current_minute = now_utc.minute
    
    # Calculate which slot should run (0-19 based on 15-min intervals in 5-hour window)
    # Slot 0 = :00, Slot 1 = :15, Slot 2 = :30, Slot 3 = :45
    current_slot_in_hour = current_minute // 15  # 0, 1, 2, or 3
    
    print(f"🕐 [Scheduler] Running scan check at {now_utc.strftime('%H:%M')} UTC (slot {current_slot_in_hour})")
    
    try:
        async with async_session() as db:
            settings_service = SystemSettingsService(db)
            
            # Check kill switches
            if not await settings_service.is_scanning_enabled():
                print("⛔ [Scheduler] ABORTED - Scanning disabled")
                return
            
            if not await settings_service.is_daily_scans_enabled():
                print("⛔ [Scheduler] ABORTED - Daily scans disabled")
                return
            
            # Find stores where local time is 1-6 AM and it's their scan slot
            # Also exclude stores already being scanned
            result = await db.execute(
                select(Store).where(
                    Store.is_active == True,
                    Store.access_token.isnot(None),
                    Store.scan_in_progress == False
                )
            )
            all_stores = result.scalars().all()
        
        # Filter stores by timezone (local time must be 1-6 AM)
        stores_to_scan = []
        
        for store in all_stores:
            try:
                # Get store's local time
                tz = ZoneInfo(store.timezone or "UTC")
                local_time = datetime.now(tz)
                local_hour = local_time.hour
                
                # Check if within 1-6 AM window
                if SCAN_WINDOW_START <= local_hour < SCAN_WINDOW_END:
                    # Calculate which slot this store belongs to
                    # Hours 1-5 = 5 hours, each hour has 4 slots = 20 slots total
                    hour_offset = local_hour - SCAN_WINDOW_START  # 0-4
                    store_slot = (hour_offset * 4) + current_slot_in_hour
                    
                    # Check if it's this store's slot
                    if store.scan_slot == store_slot:
                        stores_to_scan.append(store)
            except Exception as e:
                # Invalid timezone, default to scanning
                print(f"⚠️ [Scheduler] Invalid timezone for {store.shopify_domain}: {e}")
        
        if not stores_to_scan:
            print(f"😴 [Scheduler] No stores due for scanning this slot")
            return
        
        print(f"📋 [Scheduler] Found {len(stores_to_scan)} stores to scan")
        
        # Process in parallel batches
        successful = 0
        failed = 0
        
        for i in range(0, len(stores_to_scan), PARALLEL_BATCH_SIZE):
            batch = stores_to_scan[i:i + PARALLEL_BATCH_SIZE]
            batch_num = (i // PARALLEL_BATCH_SIZE) + 1
            total_batches = (len(stores_to_scan) + PARALLEL_BATCH_SIZE - 1) // PARALLEL_BATCH_SIZE
            
            print(f"🔄 [Scheduler] Batch {batch_num}/{total_batches} ({len(batch)} stores)...")
            
            async def scan_store_with_status(store):
                store_id = store.id
                store_domain = store.shopify_domain
                
                try:
                    async with async_session() as store_db:
                        # Mark scan as in progress
                        result = await store_db.execute(
                            select(Store).where(Store.id == store_id)
                        )
                        db_store = result.scalar_one()
                        db_store.scan_in_progress = True
                        db_store.last_scan_started_at = datetime.utcnow()
                        await store_db.commit()
                        
                        # Run scan with timeout
                        try:
                            scan_service = DailyScanService(store_db)
                            scan = await asyncio.wait_for(
                                scan_service.run_daily_scan(db_store),
                                timeout=SCAN_TIMEOUT_MINUTES * 60
                            )
                            await store_db.commit()
                            
                            # Update success status
                            db_store.scan_in_progress = False
                            db_store.last_scan_completed_at = datetime.utcnow()
                            db_store.last_scan_status = "success"
                            db_store.last_scan_error = None
                            db_store.scan_failure_count = 0
                            db_store.needs_extended_scan = False
                            await store_db.commit()
                            
                            print(f"✅ [Scheduler] {store_domain}: {scan.risk_level} risk")
                            return True
                            
                        except asyncio.TimeoutError:
                            db_store.scan_in_progress = False
                            db_store.last_scan_completed_at = datetime.utcnow()
                            db_store.last_scan_status = "timeout"
                            db_store.last_scan_error = f"Scan exceeded {SCAN_TIMEOUT_MINUTES} minute timeout"
                            db_store.scan_failure_count = (db_store.scan_failure_count or 0) + 1
                            if db_store.scan_failure_count >= 2:
                                db_store.needs_extended_scan = True
                            await store_db.commit()
                            
                            print(f"⏱️ [Scheduler] {store_domain}: TIMEOUT")
                            return False
                            
                except Exception as e:
                    # Update failure status
                    try:
                        async with async_session() as err_db:
                            result = await err_db.execute(
                                select(Store).where(Store.id == store_id)
                            )
                            db_store = result.scalar_one()
                            db_store.scan_in_progress = False
                            db_store.last_scan_completed_at = datetime.utcnow()
                            db_store.last_scan_status = "failed"
                            db_store.last_scan_error = str(e)[:500]
                            db_store.scan_failure_count = (db_store.scan_failure_count or 0) + 1
                            if db_store.scan_failure_count >= 2:
                                db_store.needs_extended_scan = True
                            await err_db.commit()
                    except:
                        pass
                    
                    print(f"❌ [Scheduler] {store_domain}: {e}")
                    return False
            
            results = await asyncio.gather(*[scan_store_with_status(store) for store in batch])
            
            successful += sum(1 for r in results if r)
            failed += sum(1 for r in results if not r)
            
            if i + PARALLEL_BATCH_SIZE < len(stores_to_scan):
                await asyncio.sleep(5)
        
        print(f"🏁 [Scheduler] Scan batch complete: {successful} success, {failed} failed")
        
    except Exception as e:
        print(f"❌ [Scheduler] Scheduler error: {e}")


async def run_data_retention():
    """
    Run data retention cleanup for all stores
    Deletes old theme snapshots based on plan tier
    """
    from app.db.database import async_session
    from app.services.data_retention_service import DataRetentionService
    from app.services.system_settings_service import SystemSettingsService
    
    print("🗑️ [Retention] Starting data retention cleanup...")
    
    try:
        async with async_session() as db:
            # Check if system is enabled
            settings_service = SystemSettingsService(db)
            if not await settings_service.is_scanning_enabled():
                print("⛔ [Retention] ABORTED - System is disabled")
                return
            
            retention_service = DataRetentionService(db)
            summary = await retention_service.prune_all_stores()
            await db.commit()
            
            print(f"✅ [Retention] Cleanup complete:")
            print(f"   Stores processed: {summary['stores_processed']}")
            print(f"   Theme files deleted: {summary['total_theme_files_deleted']}")
            print(f"   Scans deleted: {summary['total_scans_deleted']}")
            print(f"   Script snapshots deleted: {summary['total_script_snapshots_deleted']}")
            
            if summary['errors']:
                print(f"   ⚠️ Errors: {len(summary['errors'])}")
                
    except Exception as e:
        print(f"❌ [Retention] Cleanup failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events
    """
    # Startup: Initialize database
    print("🔍 Starting Sherlock - Shopify App Diagnostics...")
    print(f"Environment: {settings.environment}")
    print(f"Debug mode: {settings.debug}")
    
    try:
        await init_db()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"⚠️  Database initialization warning: {e}")
        print("   (This is normal if database doesn't exist yet)")
    
    # Initialize system settings (kill switches, rate limits)
    try:
        from app.db.database import async_session
        from app.services.system_settings_service import SystemSettingsService
        
        async with async_session() as db:
            settings_service = SystemSettingsService(db)
            created = await settings_service.initialize_defaults()
            await db.commit()
            if created:
                print(f"✅ Initialized {len(created)} system settings")
            else:
                print("✅ System settings already configured")
    except Exception as e:
        print(f"⚠️  System settings initialization warning: {e}")
    
    # Start the scheduler for daily scans
    # Runs every 15 minutes, scans stores where local time is 1-6 AM
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    
    scheduler.add_job(
        run_scheduled_daily_scans,
        IntervalTrigger(minutes=15),
        id="daily_scans",
        name="Daily store scans (timezone-aware)",
        replace_existing=True
    )
    
    # Data retention cleanup - runs daily at 4 AM UTC
    scheduler.add_job(
        run_data_retention,
        CronTrigger(hour=4, minute=0),
        id="data_retention",
        name="Data retention cleanup",
        replace_existing=True
    )
    
    scheduler.start()
    print("⏰ Scheduler started - Scans every 15 min (1-6 AM local time per store)")
    print("🗑️ Data retention scheduled - Daily at 4 AM UTC")
    
    yield
    
    # Shutdown
    scheduler.shutdown()
    print("👋 Shutting down Sherlock...")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="Diagnose which Shopify app is causing issues in your store",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers (auth, webhooks, etc.)
app.include_router(api_router, prefix="/api/v1")

# Also include auth router at root level for cleaner OAuth URLs
from app.api.routers.auth import router as auth_router
app.include_router(auth_router)

# Mount static files
import os
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


# ==================== Dashboard Routes ====================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, shop: Optional[str] = None):
    """
    Serve the main dashboard HTML page.
    
    Usage: /dashboard?shop=my-store.myshopify.com
    """
    templates_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    
    if os.path.exists(templates_path):
        with open(templates_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    
    return HTMLResponse(content="""
        <html>
            <head><title>Sherlock Dashboard</title></head>
            <body>
                <h1>Dashboard template not found</h1>
                <p>Please ensure templates/dashboard.html exists.</p>
            </body>
        </html>
    """, status_code=500)


@app.get("/install", response_class=HTMLResponse)
async def install_page(request: Request):
    """
    Serve the install landing page.
    This is where merchants start the installation process.
    """
    templates_path = os.path.join(os.path.dirname(__file__), "templates", "install.html")
    
    if os.path.exists(templates_path):
        with open(templates_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    
    return HTMLResponse(content="""
        <html>
            <head><title>Install Sherlock</title></head>
            <body>
                <h1>Install page not found</h1>
            </body>
        </html>
    """, status_code=500)

@app.get("/faq", response_class=HTMLResponse)
async def faq_page(request: Request):
    """
    Serve the FAQ page for merchants.
    """
    templates_path = os.path.join(os.path.dirname(__file__), "templates", "faq.html")
    
    if os.path.exists(templates_path):
        with open(templates_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    
    return HTMLResponse(content="""
        <html>
            <head><title>FAQ - Sherlock</title></head>
            <body>
                <h1>FAQ page not found</h1>
                <p>Please ensure templates/faq.html exists.</p>
            </body>
        </html>
    """, status_code=500)

# ==================== SEO Routes ====================

@app.get("/robots.txt", include_in_schema=False)
async def robots():
    """Serve robots.txt for search engines"""
    file_path = os.path.join(os.path.dirname(__file__), "static", "robots.txt")
    return FileResponse(file_path, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    """Serve sitemap.xml for search engines"""
    file_path = os.path.join(os.path.dirname(__file__), "static", "sitemap.xml")
    return FileResponse(file_path, media_type="application/xml")

# ==================== Pydantic Models ====================

class StoreInfo(BaseModel):
    shopify_domain: str
    shop_name: Optional[str] = None
    email: Optional[str] = None


class ScanRequest(BaseModel):
    shop: str  # e.g., "my-store.myshopify.com"
    scan_type: str = "full"  # "full", "quick", "apps_only", "theme_only", "performance"


class AppInfo(BaseModel):
    app_name: str
    installed_on: Optional[datetime] = None
    is_suspect: bool = False
    risk_score: float = 0.0
    risk_reasons: Optional[List[str]] = None


class DiagnosisResult(BaseModel):
    diagnosis_id: str
    status: str
    scan_type: str
    total_apps_scanned: int
    issues_found: int
    suspect_apps: Optional[List[str]] = None
    recommendations: Optional[List[dict]] = None
    performance_score: Optional[float] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    environment: str


# ==================== Helper Functions ====================

async def get_store_by_domain(db: AsyncSession, shopify_domain: str) -> Optional[Store]:
    """Get store by Shopify domain"""
    result = await db.execute(
        select(Store).where(Store.shopify_domain == shopify_domain)
    )
    return result.scalar_one_or_none()


async def get_or_create_store(db: AsyncSession, shopify_domain: str) -> Store:
    """Get existing store or create a new one"""
    store = await get_store_by_domain(db, shopify_domain)
    if not store:
        store = Store(shopify_domain=shopify_domain)
        db.add(store)
        await db.flush()
    return store


# ==================== Background Tasks ====================

async def run_scan_background(store_id: str, diagnosis_id: str, scan_type: str):
    """Background task to run diagnostic scan"""
    from app.db.database import async_session
    
    async with async_session() as db:
        try:
            # Get store
            result = await db.execute(
                select(Store).where(Store.id == store_id)
            )
            store = result.scalar_one_or_none()
            
            if not store:
                print(f"❌ [Background] Store not found: {store_id}")
                return
            
            # Run diagnosis
            diagnosis_service = DiagnosisService(db)
            await diagnosis_service.run_diagnosis(store, diagnosis_id, scan_type)
            
            await db.commit()
            
        except Exception as e:
            print(f"❌ [Background] Scan error: {e}")
            await db.rollback()


# ==================== Core Endpoints ====================

@app.get("/")
async def root(request: Request):
    """
    Root endpoint - serves preview page for pre-launch.
    Change back to RedirectResponse(url="/install") when ready to launch.
    """
    # Check if this is a browser request
    accept_header = request.headers.get("accept", "")
    
    if "text/html" in accept_header:
        # Browser request - serve preview page (PRE-LAUNCH)
        templates_path = os.path.join(os.path.dirname(__file__), "templates", "preview.html")
        
        if os.path.exists(templates_path):
            with open(templates_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            return HTMLResponse(content=html_content)
        
        # Fallback to install page if preview doesn't exist
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/install")
    
    # API request - return health info
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "version": "1.0.0",
        "environment": settings.environment,
        "docs": "/docs",
        "install": "/install",
        "dashboard": "/dashboard"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ==================== Scan Endpoints ====================

@app.post("/api/v1/scan/start", response_model=DiagnosisResult)
async def start_scan(
    request: ScanRequest, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Start a new diagnostic scan for a store.
    
    Scan types:
    - full: Complete scan (apps + theme + performance)
    - quick: Fast check of recently installed apps only
    - apps_only: Scan installed apps and their risk factors
    - theme_only: Analyze theme code for conflicts
    - performance: Performance metrics and slow resources
    """
    try:
        # Get or create store
        store = await get_or_create_store(db, request.shop)
        
        # Create new diagnosis record
        diagnosis = Diagnosis(
            store_id=store.id,
            scan_type=request.scan_type,
            status="pending"
        )
        db.add(diagnosis)
        await db.commit()
        
        print(f"🔍 [Sherlock] Started {request.scan_type} scan for {request.shop}")
        
        # Trigger background scan
        background_tasks.add_task(
            run_scan_background, 
            store.id, 
            diagnosis.id, 
            request.scan_type
        )
        
        return DiagnosisResult(
            diagnosis_id=diagnosis.id,
            status="running",
            scan_type=diagnosis.scan_type,
            total_apps_scanned=0,
            issues_found=0,
            suspect_apps=None,
            recommendations=None,
            performance_score=None,
            started_at=diagnosis.started_at,
            completed_at=None
        )
    
    except Exception as e:
        print(f"❌ [Sherlock] Scan start error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start scan: {str(e)}")


@app.get("/api/v1/scan/{diagnosis_id}", response_model=DiagnosisResult)
async def get_scan_result(diagnosis_id: str, db: AsyncSession = Depends(get_db)):
    """Get the results of a diagnostic scan"""
    try:
        result = await db.execute(
            select(Diagnosis).where(Diagnosis.id == diagnosis_id)
        )
        diagnosis = result.scalar_one_or_none()
        
        if not diagnosis:
            raise HTTPException(status_code=404, detail="Diagnosis not found")
        
        return DiagnosisResult(
            diagnosis_id=diagnosis.id,
            status=diagnosis.status,
            scan_type=diagnosis.scan_type,
            total_apps_scanned=diagnosis.total_apps_scanned or 0,
            issues_found=diagnosis.issues_found or 0,
            suspect_apps=diagnosis.suspect_apps,
            recommendations=diagnosis.recommendations,
            performance_score=diagnosis.performance_score,
            started_at=diagnosis.started_at,
            completed_at=diagnosis.completed_at
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Get scan error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get scan results")


@app.get("/api/v1/scan/history/{shop}")
async def get_scan_history(shop: str, limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Get scan history for a store (includes both manual and auto scans)"""
    try:
        store = await get_store_by_domain(db, shop)
        if not store:
            return {"scans": []}
        
        # Get manual scans (Diagnosis)
        result = await db.execute(
            select(Diagnosis)
            .where(Diagnosis.store_id == store.id)
            .order_by(Diagnosis.started_at.desc())
            .limit(limit)
        )
        diagnoses = result.scalars().all()
        
        # Get auto scans (DailyScan)
        auto_result = await db.execute(
            select(DailyScan)
            .where(DailyScan.store_id == store.id)
            .order_by(DailyScan.started_at.desc())
            .limit(limit)
        )
        daily_scans = auto_result.scalars().all()
        
        # Combine both types
        all_scans = []
        
        for d in diagnoses:
            all_scans.append({
                "diagnosis_id": d.id,
                "scan_type": "manual",
                "status": d.status,
                "issues_found": d.issues_found or 0,
                "started_at": d.started_at.isoformat() if d.started_at else None,
                "completed_at": d.completed_at.isoformat() if d.completed_at else None
            })
        
        for s in daily_scans:
            issues = (s.files_changed or 0) + (s.css_issues_found or 0)
            all_scans.append({
                "diagnosis_id": s.id,
                "scan_type": "auto",
                "status": s.status,
                "issues_found": issues,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None
            })
        
        # Sort by date (most recent first) and limit
        all_scans.sort(key=lambda x: x["completed_at"] or x["started_at"] or "", reverse=True)
        all_scans = all_scans[:limit]
        
        return {
            "shop": shop,
            "scans": all_scans
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Scan history error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get scan history")


@app.get("/api/v1/scan/{diagnosis_id}/report")
async def get_diagnosis_report(diagnosis_id: str, db: AsyncSession = Depends(get_db)):
    """Get full diagnosis report with recommendations and summary"""
    try:
        diagnosis_service = DiagnosisService(db)
        report = await diagnosis_service.get_diagnosis_report(diagnosis_id)
        
        if not report:
            raise HTTPException(status_code=404, detail="Diagnosis not found")
        
        return report
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Get report error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get diagnosis report")


@app.get("/api/v1/scan/daily/{scan_id}/report")
async def get_daily_scan_report(scan_id: str, db: AsyncSession = Depends(get_db)):
    """Get daily auto scan report"""
    try:
        result = await db.execute(
            select(DailyScan).where(DailyScan.id == scan_id)
        )
        scan = result.scalar()
        
        if not scan:
            raise HTTPException(status_code=404, detail="Daily scan not found")
        
        return {
            "scan_id": str(scan.id),
            "scan_type": "auto",
            "status": scan.status,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
            "risk_level": scan.risk_level,
            "risk_reasons": scan.risk_reasons or [],
            "summary": scan.summary,
            "files": {
                "total": scan.files_total or 0,
                "changed": scan.files_changed or 0,
                "new": scan.files_new or 0,
                "deleted": scan.files_deleted or 0
            },
            "scripts": {
                "total": scan.scripts_total or 0,
                "new": scan.scripts_new or 0,
                "removed": scan.scripts_removed or 0
            },
            "css_issues": {
                "count": scan.css_issues_found or 0,
                "details": scan.non_namespaced_css or []
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Daily scan report error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get daily scan report")


@app.get("/api/v1/debug/token-check/{shop}")
async def debug_token_check(shop: str, db: AsyncSession = Depends(get_db)):
    """Debug endpoint to check token status"""
    result = await db.execute(select(Store).where(Store.shopify_domain == shop))
    store = result.scalar_one_or_none()
    
    if not store:
        return {"status": "NOT_FOUND"}
    
    if not store.access_token:
        return {"status": "NO_TOKEN"}
    
    return {
        "status": "TOKEN_EXISTS",
        "token_preview": store.access_token[:6] + "...",
        "token_length": len(store.access_token)
    }

@app.get("/api/v1/scan/debug/script-tags")
async def debug_script_tags(shop: str):
    """Debug endpoint to check what script tags Shopify returns"""
    import httpx
    from app.db.database import async_session
    
    async with async_session() as db:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar()
        
        if not store:
            return {"error": "Store not found"}
        
        if not store.access_token:
            return {"error": "No access token for store"}
        
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
                
                return {
                    "shop": shop,
                    "status_code": response.status_code,
                    "response": response.json() if response.status_code == 200 else response.text
                }
        except Exception as e:
            return {"shop": shop, "error": str(e)}
        
@app.get("/api/v1/scan/debug/app-blocks")
async def debug_app_blocks(shop: str):
    """Debug endpoint to check app blocks in theme settings"""
    import httpx
    import json
    from app.db.database import async_session
    
    async with async_session() as db:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar()
        
        if not store:
            return {"error": "Store not found"}
        
        if not store.access_token:
            return {"error": "No access token for store"}
        
        try:
            async with httpx.AsyncClient() as client:
                # First get the main theme
                themes_response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/2024-01/themes.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if themes_response.status_code != 200:
                    return {"error": f"Failed to fetch themes: {themes_response.status_code}"}
                
                themes = themes_response.json().get("themes", [])
                main_theme = next((t for t in themes if t.get("role") == "main"), None)
                
                if not main_theme:
                    return {"error": "No main theme found"}
                
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
                    return {"error": f"Failed to fetch settings: {settings_response.status_code}"}
                
                asset = settings_response.json().get("asset", {})
                settings_content = asset.get("value", "{}")
                
                try:
                    settings_data = json.loads(settings_content)
                except:
                    return {"error": "Failed to parse settings JSON"}
                
                # Look for app blocks in current settings
                current = settings_data.get("current", {})
                blocks = current.get("blocks", {})
                
                # Find app-related blocks
                app_blocks = {}
                for block_id, block_data in blocks.items():
                    block_type = block_data.get("type", "")
                    if "app" in block_type.lower() or block_type.startswith("shopify://apps/"):
                        app_blocks[block_id] = block_data
                
                return {
                    "shop": shop,
                    "theme_id": theme_id,
                    "theme_name": main_theme.get("name"),
                    "total_blocks": len(blocks),
                    "app_blocks_found": len(app_blocks),
                    "app_blocks": app_blocks
                }
                
        except Exception as e:
            return {"shop": shop, "error": str(e)}
        

        
@app.get("/api/v1/apps/clear-unknown/{shop}")
async def clear_unknown_apps(shop: str):
    """Clear apps with Unknown name from database"""
    from app.db.database import async_session
    from app.db.models import InstalledApp
    from sqlalchemy import delete
    
    async with async_session() as db:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar()
        
        if not store:
            return {"error": "Store not found"}
        
        # Delete apps with "Unknown" name
        delete_result = await db.execute(
            delete(InstalledApp).where(
                InstalledApp.store_id == store.id,
                InstalledApp.app_name == "Unknown"
            )
        )
        await db.commit()
        
        return {
            "success": True,
            "deleted_count": delete_result.rowcount
        }
    
@app.get("/api/v1/apps/clear-all/{shop}")
async def clear_all_apps(shop: str):
    """Clear all apps for a store to allow fresh detection"""
    from app.db.database import async_session
    from app.db.models import InstalledApp
    from sqlalchemy import delete
    
    async with async_session() as db:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar()
        
        if not store:
            return {"error": "Store not found"}
        
        # Delete all apps for this store
        delete_result = await db.execute(
            delete(InstalledApp).where(InstalledApp.store_id == store.id)
        )
        await db.commit()
        
        return {
            "success": True,
            "deleted_count": delete_result.rowcount
        }
        
# ==================== Apps Endpoint =====================

@app.get("/api/v1/apps/{shop}")
async def get_installed_apps(shop: str, db: AsyncSession = Depends(get_db)):
    """Get all installed apps for a store with risk analysis"""
    try:
        store = await get_store_by_domain(db, shop)
        if not store:
            return {"shop": shop, "apps": [], "total": 0}
        
        result = await db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store.id)
            .order_by(InstalledApp.installed_on.desc())
        )
        apps = result.scalars().all()
        
        return {
            "shop": shop,
            "total": len(apps),
            "suspect_count": sum(1 for a in apps if a.is_suspect),
            "apps": [
                {
                    "id": a.id,
                    "app_name": a.app_name,
                    "app_handle": a.app_handle,
                    "installed_on": a.installed_on.isoformat() if a.installed_on else None,
                    "first_seen": a.first_seen.isoformat() if a.first_seen else None,
                    "update_detected_at": a.update_detected_at.isoformat() if a.update_detected_at else None,
                    "is_suspect": a.is_suspect,
                    "risk_score": a.risk_score,
                    "risk_reasons": a.risk_reasons,
                    "category": a.category or "Unknown",
                    "category_reason": a.category_reason or "Sherlock is monitoring this app. No problems detected so far.",
                    "injects_scripts": a.injects_scripts,
                    "injects_theme_code": a.injects_theme_code,
                    "script_count": a.script_count,
                    "last_scanned": a.last_scanned.isoformat() if a.last_scanned else None
                }
                for a in apps
            ]
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Get apps error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get installed apps")


@app.get("/api/v1/apps/{shop}/suspects")
async def get_suspect_apps(shop: str, db: AsyncSession = Depends(get_db)):
    """Get only suspect apps (flagged as potential issues)"""
    try:
        store = await get_store_by_domain(db, shop)
        if not store:
            return {"shop": shop, "suspects": []}
        
        result = await db.execute(
            select(InstalledApp)
            .where(InstalledApp.store_id == store.id)
            .where(InstalledApp.is_suspect == True)
            .order_by(InstalledApp.risk_score.desc())
        )
        apps = result.scalars().all()
        
        return {
            "shop": shop,
            "total_suspects": len(apps),
            "suspects": [
                {
                    "app_name": a.app_name,
                    "risk_score": a.risk_score,
                    "risk_reasons": a.risk_reasons,
                    "installed_on": a.installed_on.isoformat() if a.installed_on else None,
                    "recommendation": "Consider uninstalling to test if this resolves your issue"
                }
                for a in apps
            ]
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Get suspects error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get suspect apps")


# ==================== Theme Issues Endpoints ====================

@app.get("/api/v1/theme-issues/{shop}")
async def get_theme_issues(shop: str, db: AsyncSession = Depends(get_db)):
    """Get detected theme code issues/conflicts"""
    try:
        store = await get_store_by_domain(db, shop)
        if not store:
            return {"shop": shop, "issues": []}
        
        result = await db.execute(
            select(ThemeIssue)
            .where(ThemeIssue.store_id == store.id)
            .where(ThemeIssue.is_resolved == False)
            .order_by(ThemeIssue.severity.desc())
        )
        issues = result.scalars().all()
        
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_issues = sorted(issues, key=lambda x: severity_order.get(x.severity, 99))
        
        return {
            "shop": shop,
            "total_issues": len(sorted_issues),
            "by_severity": {
                "critical": sum(1 for i in sorted_issues if i.severity == "critical"),
                "high": sum(1 for i in sorted_issues if i.severity == "high"),
                "medium": sum(1 for i in sorted_issues if i.severity == "medium"),
                "low": sum(1 for i in sorted_issues if i.severity == "low")
            },
            "issues": [
                {
                    "id": i.id,
                    "file_path": i.file_path,
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "likely_source": i.likely_source,
                    "confidence": i.confidence,
                    "line_number": i.line_number,
                    "code_snippet": i.code_snippet[:200] if i.code_snippet else None,
                    "detected_at": i.detected_at.isoformat() if i.detected_at else None
                }
                for i in sorted_issues
            ]
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Get theme issues error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get theme issues")


# ==================== Performance Endpoints ====================

@app.get("/api/v1/performance/{shop}")
async def get_performance_history(shop: str, limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Get performance snapshots history"""
    try:
        store = await get_store_by_domain(db, shop)
        if not store:
            return {"shop": shop, "snapshots": []}
        
        result = await db.execute(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.store_id == store.id)
            .order_by(PerformanceSnapshot.tested_at.desc())
            .limit(limit)
        )
        snapshots = result.scalars().all()
        
        return {
            "shop": shop,
            "total_snapshots": len(snapshots),
            "latest": {
                "performance_score": snapshots[0].performance_score if snapshots else None,
                "load_time_ms": snapshots[0].load_time_ms if snapshots else None,
                "tested_at": snapshots[0].tested_at.isoformat() if snapshots else None
            } if snapshots else None,
            "snapshots": [
                {
                    "id": s.id,
                    "performance_score": s.performance_score,
                    "load_time_ms": s.load_time_ms,
                    "time_to_first_byte_ms": s.time_to_first_byte_ms,
                    "time_to_interactive_ms": s.time_to_interactive_ms,
                    "total_requests": s.total_requests,
                    "total_size_kb": s.total_size_kb,
                    "script_count": s.script_count,
                    "third_party_script_count": s.third_party_script_count,
                    "slow_resources": s.slow_resources,
                    "blocking_scripts": s.blocking_scripts,
                    "page_tested": s.page_tested,
                    "tested_at": s.tested_at.isoformat() if s.tested_at else None
                }
                for s in snapshots
            ]
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Get performance error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get performance history")


@app.get("/api/v1/performance/{shop}/latest")
async def get_latest_performance(shop: str, db: AsyncSession = Depends(get_db)):
    """Get most recent performance snapshot"""
    try:
        store = await get_store_by_domain(db, shop)
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        result = await db.execute(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.store_id == store.id)
            .order_by(PerformanceSnapshot.tested_at.desc())
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        
        if not snapshot:
            return {"shop": shop, "message": "No performance data yet. Run a scan first."}
        
        return {
            "shop": shop,
            "performance_score": snapshot.performance_score,
            "load_time_ms": snapshot.load_time_ms,
            "time_to_first_byte_ms": snapshot.time_to_first_byte_ms,
            "time_to_interactive_ms": snapshot.time_to_interactive_ms,
            "total_requests": snapshot.total_requests,
            "total_size_kb": snapshot.total_size_kb,
            "script_count": snapshot.script_count,
            "third_party_script_count": snapshot.third_party_script_count,
            "slow_resources": snapshot.slow_resources,
            "blocking_scripts": snapshot.blocking_scripts,
            "page_tested": snapshot.page_tested,
            "tested_at": snapshot.tested_at.isoformat() if snapshot.tested_at else None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Get latest performance error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get performance data")


# ==================== Enhanced Diagnostic Endpoints ====================

from app.services.conflict_database import ConflictDatabase
from app.services.orphan_code_service import OrphanCodeService
from app.services.timeline_service import TimelineService
from app.services.community_reports_service import CommunityReportsService


@app.post("/api/v1/conflicts/check")
async def check_app_conflicts(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Check for known conflicts between installed apps.
    Returns conflicts and duplicate functionality warnings.
    """
    try:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        # Get installed apps
        apps_result = await db.execute(
            select(InstalledApp).where(InstalledApp.store_id == store.id)
        )
        installed_apps = [app.app_name for app in apps_result.scalars().all()]
        
        # Check conflicts
        conflict_db = ConflictDatabase()
        conflicts = conflict_db.check_conflicts(installed_apps)
        duplicates = conflict_db.get_duplicate_functionality_apps(installed_apps)
        
        return {
            "shop": shop,
            "installed_apps_count": len(installed_apps),
            "conflicts_found": len(conflicts),
            "conflicts": conflicts,
            "duplicate_functionality": duplicates,
            "has_critical": any(c["severity"] == "critical" for c in conflicts)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Check conflicts error: {e}")
        raise HTTPException(status_code=500, detail="Failed to check conflicts")


@app.post("/api/v1/orphan-code/scan")
async def scan_orphan_code(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Scan for leftover code from uninstalled apps.
    This orphan code can slow down your store and cause issues.
    """
    try:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        orphan_service = OrphanCodeService(db)
        results = await orphan_service.scan_for_orphan_code(store)
        
        return results
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Orphan code scan error: {e}")
        raise HTTPException(status_code=500, detail="Failed to scan orphan code")


@app.get("/api/v1/orphan-code/cleanup/{app_name}")
async def get_cleanup_instructions(
    app_name: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed cleanup instructions for removing leftover code from an app.
    """
    try:
        orphan_service = OrphanCodeService(db)
        instructions = await orphan_service.get_cleanup_instructions(app_name)
        
        if not instructions:
            return {
                "app": app_name,
                "instructions_available": False,
                "message": "No cleanup instructions available for this app"
            }
        
        return {
            "app": app_name,
            "instructions_available": True,
            **instructions
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Get cleanup instructions error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get cleanup instructions")


@app.get("/api/v1/timeline/{shop}")
async def get_store_timeline(
    shop: str,
    days: int = 90,
    db: AsyncSession = Depends(get_db)
):
    """
    Get timeline of app installations and performance changes.
    Shows correlations between installs and performance degradation.
    """
    try:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        timeline_service = TimelineService(db)
        timeline = await timeline_service.build_store_timeline(store, days=days)
        
        return timeline
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Get timeline error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get timeline")


@app.get("/api/v1/timeline/{shop}/compare/{app_id}")
async def compare_before_after(
    shop: str,
    app_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Compare store performance before and after a specific app was installed.
    """
    try:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        timeline_service = TimelineService(db)
        comparison = await timeline_service.compare_before_after(store, app_id)
        
        return comparison
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Compare before/after error: {e}")
        raise HTTPException(status_code=500, detail="Failed to compare")


@app.get("/api/v1/timeline/{shop}/impact-ranking")
async def get_impact_ranking(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get apps ranked by their estimated performance impact.
    Most impactful (negative) apps are listed first.
    """
    try:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        timeline_service = TimelineService(db)
        rankings = await timeline_service.get_performance_impact_ranking(store)
        
        return {
            "shop": shop,
            "rankings": rankings
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Get impact ranking error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get rankings")


@app.get("/api/v1/timeline/{shop}/removal-order")
async def get_removal_order(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get suggested order for testing app removals.
    Based on risk scores, performance impact, and install dates.
    """
    try:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        timeline_service = TimelineService(db)
        suggestions = await timeline_service.suggest_removal_order(store)
        
        return {
            "shop": shop,
            "removal_order": suggestions
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Get removal order error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get removal order")


@app.post("/api/v1/community/insights")
async def get_community_insights(
    shop: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get community-reported issues for installed apps.
    Surfaces known problems from Shopify forums, Reddit, etc.
    """
    try:
        result = await db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        # Get installed apps
        apps_result = await db.execute(
            select(InstalledApp).where(InstalledApp.store_id == store.id)
        )
        installed_apps = [app.app_name for app in apps_result.scalars().all()]
        
        community_service = CommunityReportsService(db)
        insights = community_service.generate_community_insights(installed_apps)
        
        return {
            "shop": shop,
            **insights
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Sherlock] Get community insights error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get community insights")


@app.get("/api/v1/community/app/{app_name}")
async def get_app_community_report(
    app_name: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed community report for a specific app.
    Includes common issues, symptoms, and resolution rate.
    """
    try:
        community_service = CommunityReportsService(db)
        report = community_service.get_app_community_report(app_name)
        
        if not report:
            return {
                "app": app_name,
                "found": False,
                "message": "No community reports found for this app"
            }
        
        return {
            "app": app_name,
            "found": True,
            **report
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Get app community report error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get report")


@app.get("/api/v1/community/trending")
async def get_trending_issues(
    months: int = 3,
    db: AsyncSession = Depends(get_db)
):
    """
    Get currently trending issues in the Shopify community.
    """
    try:
        community_service = CommunityReportsService(db)
        trending = community_service.get_trending_issues(months=months)
        top_apps = community_service.get_apps_by_issue_count(limit=10)
        
        return {
            "trending_issues": trending,
            "most_reported_apps": top_apps
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Get trending issues error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get trending issues")


class SymptomMatchRequest(BaseModel):
    keywords: List[str]


@app.post("/api/v1/community/match-symptoms")
async def match_symptoms_to_apps(
    request: SymptomMatchRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Find apps that match described symptoms.
    Example keywords: ["slow", "mobile", "checkout"]
    """
    try:
        community_service = CommunityReportsService(db)
        matches = community_service.get_symptoms_matching(request.keywords)
        
        return {
            "keywords": request.keywords,
            "matches": matches
        }
    
    except Exception as e:
        print(f"❌ [Sherlock] Match symptoms error: {e}")
        raise HTTPException(status_code=500, detail="Failed to match symptoms")


# ==================== GDPR Compliance Endpoints ====================

class CustomerRedactRequest(BaseModel):
    shopify_domain: str
    customer_id: Optional[str] = None
    customer_email: Optional[str] = None


class ShopRedactRequest(BaseModel):
    shopify_domain: str


@app.post("/api/v1/gdpr/customers/redact")
async def gdpr_redact_customer(payload: CustomerRedactRequest, db: AsyncSession = Depends(get_db)):
    """
    GDPR: Redact customer data.
    Sherlock doesn't store customer PII, so this is a no-op acknowledgment.
    """
    print(f"📋 [GDPR] Customer redact request for {payload.shopify_domain}")
    return {
        "success": True,
        "message": "Sherlock does not store customer PII. No action required."
    }


@app.post("/api/v1/gdpr/shop/redact")
async def gdpr_redact_shop(payload: ShopRedactRequest, db: AsyncSession = Depends(get_db)):
    """
    GDPR: Redact all shop data.
    Called 48 hours after app uninstall.
    """
    try:
        store = await get_store_by_domain(db, payload.shopify_domain)
        
        if not store:
            return {"success": True, "message": "Store not found or already deleted"}
        
        # Delete the store (cascades to all related data)
        await db.delete(store)
        await db.commit()
        
        print(f"🗑️ [GDPR] Deleted all data for {payload.shopify_domain}")
        return {"success": True, "message": "All store data deleted"}
    
    except Exception as e:
        print(f"❌ [GDPR] Shop redact error: {e}")
        raise HTTPException(status_code=500, detail="Error redacting shop data")


@app.post("/api/v1/stores/deregister")
async def deregister_store(payload: ShopRedactRequest, db: AsyncSession = Depends(get_db)):
    """
    Deregister a store (soft delete).
    Called immediately when app is uninstalled.
    """
    try:
        store = await get_store_by_domain(db, payload.shopify_domain)
        
        if not store:
            return {"success": True, "message": "Store not found"}
        
        store.is_active = False
        await db.commit()
        
        print(f"👋 [Store] Deregistered {payload.shopify_domain}")
        return {"success": True, "message": "Store deregistered"}
    
    except Exception as e:
        print(f"❌ [Store] Deregister error: {e}")
        raise HTTPException(status_code=500, detail="Error deregistering store")

@app.get("/api/v1/scan/store-diagnosis/{shop}")
async def get_store_diagnosis(shop: str, db: AsyncSession = Depends(get_db)):
    """
    Get full diagnosis for a store.
    Identifies issues, correlates with recent apps, and provides actions.
    """
    from app.services.issue_correlation_service import IssueCorrelationService
    
    service = IssueCorrelationService(db)
    diagnosis = await service.get_store_diagnosis(shop)
    
    return diagnosis


@app.get("/api/v1/scan/clear-issues/{shop}")
async def clear_theme_issues(shop: str, db: AsyncSession = Depends(get_db)):
    """
    Clear all theme issues for a store (debug endpoint)
    """
    from sqlalchemy import delete
    
    store = await get_store_by_domain(db, shop)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    delete_result = await db.execute(
        delete(ThemeIssue).where(ThemeIssue.store_id == store.id)
    )
    await db.commit()
    
    return {
        "success": True,
        "message": f"Cleared theme issues for {shop}",
        "deleted_count": delete_result.rowcount
    }


# ==================== Run Server ====================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
