"""
Sherlock - Billing Router
API endpoints for subscription management
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from billing_service import get_billing_service

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/subscribe/{plan}")
async def create_subscription(
    plan: str,
    shop: str = Query(..., description="Shop domain"),
    test: bool = Query(False, description="Test mode (no real charges)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new subscription and redirect to Shopify approval page
    
    Args:
        plan: 'standard' or 'professional'
        shop: The shop domain
        test: If true, creates test subscription
    """
    if plan not in ["standard", "professional"]:
        raise HTTPException(status_code=400, detail="Invalid plan. Must be 'standard' or 'professional'")
    
    billing_service = get_billing_service(db)
    
    # Return URL after merchant approves/declines
    return_url = f"https://app.codenamesherlock.com/api/v1/billing/callback?shop={shop}"
    
    try:
        result = await billing_service.create_subscription(
            shop=shop,
            plan_key=plan,
            return_url=return_url,
            test=test
        )
        
        # Redirect merchant to Shopify's approval page
        return RedirectResponse(url=result["confirmation_url"], status_code=303)
        
    except Exception as e:
        print(f"❌ [Billing] Error creating subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def billing_callback(
    shop: str = Query(...),
    charge_id: str = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Handle callback from Shopify after merchant approves/declines subscription
    
    Shopify redirects here after the merchant makes a decision
    """
    billing_service = get_billing_service(db)
    
    try:
        # Check the current subscription status
        status = await billing_service.get_subscription_status(shop)
        
        if status.get("has_subscription"):
            # Subscription approved - redirect to dashboard
            print(f"✅ [Billing] Subscription activated for {shop}")
            return RedirectResponse(
                url=f"https://app.codenamesherlock.com/dashboard?shop={shop}&billing=success",
                status_code=303
            )
        else:
            # Subscription declined or pending
            print(f"⚠️ [Billing] Subscription not active for {shop}: {status.get('status')}")
            return RedirectResponse(
                url=f"https://app.codenamesherlock.com/dashboard?shop={shop}&billing=declined",
                status_code=303
            )
            
    except Exception as e:
        print(f"❌ [Billing] Callback error: {e}")
        return RedirectResponse(
            url=f"https://app.codenamesherlock.com/dashboard?shop={shop}&billing=error",
            status_code=303
        )


@router.get("/status")
async def get_subscription_status(
    shop: str = Query(..., description="Shop domain"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current subscription status for a shop
    """
    billing_service = get_billing_service(db)
    
    try:
        status = await billing_service.get_subscription_status(shop)
        return status
        
    except Exception as e:
        print(f"❌ [Billing] Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_subscription(
    shop: str = Query(..., description="Shop domain"),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel an active subscription
    """
    billing_service = get_billing_service(db)
    
    try:
        result = await billing_service.cancel_subscription(shop)
        return result
        
    except Exception as e:
        print(f"❌ [Billing] Error cancelling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plans")
async def get_plans():
    """
    Get available subscription plans
    """
    return {
        "plans": [
            {
                "key": "standard",
                "name": "Sherlock Standard",
                "price": 29.00,
                "currency": "USD",
                "interval": "month",
                "trial_days": 14,
                "features": [
                    "24/7 theme monitoring",
                    "App conflict detection",
                    "7-day file history",
                    "One-click rollback",
                    "Email support"
                ]
            },
            {
                "key": "professional",
                "name": "Sherlock Professional",
                "price": 69.00,
                "currency": "USD",
                "interval": "month",
                "trial_days": 14,
                "features": [
                    "Everything in Standard",
                    "30-day file history",
                    "Priority support",
                    "Advanced diagnostics",
                    "Custom scan scheduling"
                ]
            }
        ]
    }