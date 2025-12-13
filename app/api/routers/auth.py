"""
Sherlock - Authentication Router
Handles Shopify OAuth flow and webhooks
"""

from fastapi import APIRouter, HTTPException, Request, Depends, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.shopify_auth_service import ShopifyAuthService
from app.core.config import settings


router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory state storage (use Redis in production)
_oauth_states: Dict[str, str] = {}


class InstallRequest(BaseModel):
    shop: str


class InstallResponse(BaseModel):
    install_url: str
    state: str


# ==================== OAuth Endpoints ====================

@router.get("/shopify")
async def shopify_auth_redirect(shop: str, db: AsyncSession = Depends(get_db)):
    """
    Start Shopify OAuth flow.
    Redirects merchant to Shopify to authorize the app.
    
    Usage: GET /auth/shopify?shop=my-store.myshopify.com
    """
    if not shop:
        raise HTTPException(status_code=400, detail="Shop parameter is required")
    
    auth_service = ShopifyAuthService(db)
    
    # Generate install URL
    redirect_uri = f"{settings.app_url}/api/v1/auth/callback"
    install_url, state = auth_service.generate_install_url(shop, redirect_uri)
    
    # Store state for verification
    _oauth_states[state] = shop
    
    print(f"🔐 [Auth] Redirecting {shop} to Shopify OAuth")
    
    return RedirectResponse(url=install_url)


@router.post("/shopify/install", response_model=InstallResponse)
async def get_install_url(request: InstallRequest, db: AsyncSession = Depends(get_db)):
    """
    Get Shopify install URL without redirecting.
    Useful for embedded apps or custom install flows.
    
    Returns the URL that the merchant should visit to install the app.
    """
    auth_service = ShopifyAuthService(db)
    
    redirect_uri = f"{settings.app_url}/api/v1/auth/callback"
    install_url, state = auth_service.generate_install_url(request.shop, redirect_uri)
    
    # Store state for verification
    _oauth_states[state] = request.shop
    
    return InstallResponse(install_url=install_url, state=state)


@router.get("/callback")
async def shopify_auth_callback(
    request: Request,
    shop: str,
    code: str,
    state: str,
    hmac: str,
    timestamp: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Shopify OAuth callback.
    Exchanges authorization code for access token.
    
    This endpoint is called by Shopify after merchant approves the app.
    """
    # Verify state (CSRF protection)
    stored_shop = _oauth_states.pop(state, None)
    if not stored_shop:
        print(f"⚠️ [Auth] Invalid state parameter")
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    
    # Verify HMAC
    auth_service = ShopifyAuthService(db)
    query_params = dict(request.query_params)
    
    # Note: In production, verify HMAC here
    # if not auth_service.verify_request(query_params.copy()):
    #     raise HTTPException(status_code=400, detail="Invalid HMAC")
    
    try:
        # Exchange code for access token
        token_data = await auth_service.exchange_code_for_token(shop, code)
        
        # Store the access token
        store = await auth_service.store_access_token(
            shop=shop,
            access_token=token_data["access_token"],
            scope=token_data["scope"]
        )
        
        await db.commit()
        
        print(f"✅ [Auth] Successfully installed for {shop}")
        
        # Redirect to app or success page
        # In production, redirect to your app's dashboard
        success_url = f"{settings.app_url}/auth/success?shop={shop}"
        return RedirectResponse(url=success_url)
        
    except Exception as e:
        print(f"❌ [Auth] Callback error: {e}")
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")


@router.get("/success")
async def auth_success(shop: str):
    """
    Authentication success page.
    Shown after successful app installation.
    """
    return {
        "success": True,
        "message": f"Sherlock successfully installed on {shop}!",
        "next_steps": [
            "Your store is now connected",
            "Run your first diagnostic scan",
            "Visit the dashboard to view results"
        ],
        "dashboard_url": f"/dashboard?shop={shop}",
        "api_docs": "/docs"
    }


@router.get("/verify")
async def verify_installation(shop: str, db: AsyncSession = Depends(get_db)):
    """
    Verify if a shop has the app installed and active.
    
    Returns installation status and basic store info.
    """
    auth_service = ShopifyAuthService(db)
    store = await auth_service.get_store_by_domain(shop)
    
    if not store:
        return {
            "installed": False,
            "shop": shop,
            "message": "App not installed"
        }
    
    return {
        "installed": store.is_active and store.access_token is not None,
        "shop": store.shopify_domain,
        "shop_name": store.shop_name,
        "installed_at": store.installed_at.isoformat() if store.installed_at else None,
        "is_active": store.is_active
    }


# ==================== Webhook Endpoints ====================

@router.post("/webhooks/app/uninstalled")
async def webhook_app_uninstalled(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Webhook: App Uninstalled
    Called by Shopify when merchant uninstalls the app.
    
    Required webhook topic: app/uninstalled
    """
    # Get raw body for HMAC verification
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")
    
    # Verify webhook
    auth_service = ShopifyAuthService(db)
    if settings.shopify_api_secret and not await auth_service.verify_webhook(body, hmac_header):
        print("⚠️ [Webhook] Invalid HMAC signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    # Parse payload
    import json
    try:
        payload = json.loads(body)
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    shop = request.headers.get("X-Shopify-Shop-Domain", payload.get("domain", ""))
    
    if shop:
        # Revoke access
        await auth_service.revoke_access_token(shop)
        await db.commit()
        
        print(f"👋 [Webhook] App uninstalled from {shop}")
    
    return Response(status_code=200)


@router.post("/webhooks/shop/update")
async def webhook_shop_update(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Webhook: Shop Update
    Called when shop details are updated.
    
    Required webhook topic: shop/update
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")
    
    auth_service = ShopifyAuthService(db)
    if settings.shopify_api_secret and not await auth_service.verify_webhook(body, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    import json
    try:
        payload = json.loads(body)
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    shop = request.headers.get("X-Shopify-Shop-Domain", "")
    
    if shop:
        # Update shop info
        store = await auth_service.get_store_by_domain(shop)
        if store:
            store.shop_name = payload.get("name", store.shop_name)
            store.email = payload.get("email", store.email)
            store.plan_name = payload.get("plan_name", store.plan_name)
            await db.commit()
            
            print(f"📝 [Webhook] Shop updated: {shop}")
    
    return Response(status_code=200)


@router.post("/webhooks/customers/data_request")
async def webhook_customer_data_request(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Webhook: Customer Data Request
    GDPR - Called when a customer requests their data.
    
    Required webhook topic: customers/data_request
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")
    
    auth_service = ShopifyAuthService(db)
    if settings.shopify_api_secret and not await auth_service.verify_webhook(body, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    # Sherlock doesn't store customer PII, so we just acknowledge
    print("📋 [GDPR] Customer data request received - no PII stored")
    
    return Response(status_code=200)


@router.post("/webhooks/customers/redact")
async def webhook_customer_redact(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Webhook: Customer Redact
    GDPR - Called when a customer's data should be deleted.
    
    Required webhook topic: customers/redact
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")
    
    auth_service = ShopifyAuthService(db)
    if settings.shopify_api_secret and not await auth_service.verify_webhook(body, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    # Sherlock doesn't store customer PII, so we just acknowledge
    print("📋 [GDPR] Customer redact request received - no PII stored")
    
    return Response(status_code=200)


@router.post("/webhooks/shop/redact")
async def webhook_shop_redact(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Webhook: Shop Redact
    GDPR - Called 48 hours after app uninstall to delete all shop data.
    
    Required webhook topic: shop/redact
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")
    
    auth_service = ShopifyAuthService(db)
    if settings.shopify_api_secret and not await auth_service.verify_webhook(body, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    import json
    try:
        payload = json.loads(body)
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    shop = payload.get("shop_domain", "")
    
    if shop:
        # Delete all store data
        from sqlalchemy import delete
        from app.db.models import Store
        
        store = await auth_service.get_store_by_domain(shop)
        if store:
            await db.delete(store)
            await db.commit()
            print(f"🗑️ [GDPR] All data deleted for {shop}")
    
    return Response(status_code=200)

@router.get("/debug/scopes")
async def debug_scopes(shop: str, db: AsyncSession = Depends(get_db)):
    """Debug: Check what scopes the current token has"""
    import httpx
    
    auth_service = ShopifyAuthService(db)
    store = await auth_service.get_store_by_domain(shop)
    
    if not store or not store.access_token:
        return {"error": "Store not found or no token"}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://{store.shopify_domain}/admin/oauth/access_scopes.json",
            headers={"X-Shopify-Access-Token": store.access_token}
        )
        
        return {
            "shop": store.shopify_domain,
            "status_code": response.status_code,
            "scopes": response.json() if response.status_code == 200 else response.text
        }