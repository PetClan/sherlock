"""
Sherlock - Shopify Billing Service
Handles subscription creation, status checking, and management via GraphQL API
"""

import httpx
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.config import settings
from app.db.models import Store


class BillingService:
    """Service for handling Shopify Billing API operations"""
    
    # Plan definitions
    PLANS = {
        "standard": {
            "name": "Sherlock Standard",
            "price": 29.00,
            "interval": "EVERY_30_DAYS",
            "trial_days": 14,
            "features": {
                "retention_days": 7,
                "support": "email"
            }
        },
        "professional": {
            "name": "Sherlock Professional", 
            "price": 69.00,
            "interval": "EVERY_30_DAYS",
            "trial_days": 14,
            "features": {
                "retention_days": 30,
                "support": "priority"
            }
        }
    }
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_subscription(
        self, 
        shop: str, 
        plan_key: str,
        return_url: str,
        test: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new subscription for a shop
        
        Args:
            shop: The shop domain
            plan_key: 'standard' or 'professional'
            return_url: URL to redirect after merchant approves
            test: If True, creates a test charge (no real billing)
        
        Returns:
            Dict with confirmation_url and subscription_id
        """
        if plan_key not in self.PLANS:
            raise ValueError(f"Invalid plan: {plan_key}")
        
        plan = self.PLANS[plan_key]
        
        # Get store's access token
        store = await self._get_store(shop)
        if not store or not store.access_token:
            raise Exception(f"No access token found for {shop}")
        
        # GraphQL mutation for creating subscription
        mutation = """
        mutation AppSubscriptionCreate($name: String!, $lineItems: [AppSubscriptionLineItemInput!]!, $returnUrl: URL!, $trialDays: Int, $test: Boolean) {
            appSubscriptionCreate(
                name: $name
                returnUrl: $returnUrl
                trialDays: $trialDays
                test: $test
                lineItems: $lineItems
            ) {
                userErrors {
                    field
                    message
                }
                confirmationUrl
                appSubscription {
                    id
                    status
                    trialDays
                }
            }
        }
        """
        
        variables = {
            "name": plan["name"],
            "returnUrl": return_url,
            "trialDays": plan["trial_days"],
            "test": test,
            "lineItems": [
                {
                    "plan": {
                        "appRecurringPricingDetails": {
                            "price": {
                                "amount": plan["price"],
                                "currencyCode": "USD"
                            },
                            "interval": plan["interval"]
                        }
                    }
                }
            ]
        }
        
        # Make GraphQL request
        result = await self._graphql_request(shop, store.access_token, mutation, variables)
        
        data = result.get("data", {}).get("appSubscriptionCreate", {})
        
        # Check for errors
        user_errors = data.get("userErrors", [])
        if user_errors:
            error_msg = "; ".join([e["message"] for e in user_errors])
            print(f"❌ [Billing] Subscription creation failed: {error_msg}")
            raise Exception(f"Billing error: {error_msg}")
        
        confirmation_url = data.get("confirmationUrl")
        subscription = data.get("appSubscription", {})
        subscription_id = subscription.get("id")
        
        if not confirmation_url:
            raise Exception("No confirmation URL returned from Shopify")
        
        # Store pending subscription info
        await self._update_store_subscription(
            shop=shop,
            subscription_id=subscription_id,
            status="pending",
            plan_key=plan_key
        )
        
        print(f"✅ [Billing] Created subscription for {shop}: {subscription_id}")
        
        return {
            "confirmation_url": confirmation_url,
            "subscription_id": subscription_id,
            "status": "pending"
        }
    
    async def get_subscription_status(self, shop: str) -> Dict[str, Any]:
        """
        Get current subscription status for a shop
        
        Args:
            shop: The shop domain
        
        Returns:
            Dict with subscription details
        """
        store = await self._get_store(shop)
        if not store or not store.access_token:
            return {"status": "not_installed", "has_subscription": False}
        
        # Query current app installation
        query = """
        query {
            currentAppInstallation {
                activeSubscriptions {
                    id
                    name
                    status
                    trialDays
                    currentPeriodEnd
                    lineItems {
                        plan {
                            pricingDetails {
                                ... on AppRecurringPricing {
                                    price {
                                        amount
                                        currencyCode
                                    }
                                    interval
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        result = await self._graphql_request(shop, store.access_token, query, {})
        
        data = result.get("data", {}).get("currentAppInstallation", {})
        subscriptions = data.get("activeSubscriptions", [])
        
        if not subscriptions:
            # No Shopify subscription - check local trial status
            on_trial = False
            trial_days_remaining = 0
            
            if store.trial_ends_at:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                trial_end = store.trial_ends_at
                if trial_end.tzinfo is None:
                    trial_end = trial_end.replace(tzinfo=timezone.utc)
                
                if trial_end > now:
                    on_trial = True
                    trial_days_remaining = (trial_end - now).days
            
            return {
                "status": "trial" if on_trial else "none",
                "has_subscription": False,
                "plan": store.sherlock_plan or "standard",
                "on_trial": on_trial,
                "trial_days_remaining": trial_days_remaining,
                "trial_ends_at": store.trial_ends_at.isoformat() if store.trial_ends_at else None
            }
        
        # Get the first active subscription
        sub = subscriptions[0]
        
        # Determine plan from name or price
        plan_key = self._determine_plan_from_subscription(sub)
        
        # Update local store record
        await self._update_store_subscription(
            shop=shop,
            subscription_id=sub.get("id"),
            status=sub.get("status", "").lower(),
            plan_key=plan_key
        )
        
        # Check if currently in trial (Shopify tracks this)
        shopify_trial_days = sub.get("trialDays", 0)
        on_trial = shopify_trial_days is not None and shopify_trial_days > 0
        
        return {
            "status": sub.get("status", "").lower(),
            "has_subscription": sub.get("status") == "ACTIVE",
            "plan": plan_key,
            "subscription_id": sub.get("id"),
            "name": sub.get("name"),
            "on_trial": on_trial,
            "trial_days_remaining": shopify_trial_days if on_trial else 0,
            "current_period_end": sub.get("currentPeriodEnd")
        }
    
    async def cancel_subscription(self, shop: str) -> Dict[str, Any]:
        """
        Cancel an active subscription
        
        Args:
            shop: The shop domain
        
        Returns:
            Dict with cancellation result
        """
        store = await self._get_store(shop)
        if not store or not store.access_token:
            raise Exception(f"No access token found for {shop}")
        
        # First get the active subscription ID
        status = await self.get_subscription_status(shop)
        if not status.get("has_subscription"):
            return {"success": False, "message": "No active subscription to cancel"}
        
        subscription_id = status.get("subscription_id")
        
        mutation = """
        mutation AppSubscriptionCancel($id: ID!) {
            appSubscriptionCancel(id: $id) {
                userErrors {
                    field
                    message
                }
                appSubscription {
                    id
                    status
                }
            }
        }
        """
        
        variables = {"id": subscription_id}
        
        result = await self._graphql_request(shop, store.access_token, mutation, variables)
        
        data = result.get("data", {}).get("appSubscriptionCancel", {})
        
        user_errors = data.get("userErrors", [])
        if user_errors:
            error_msg = "; ".join([e["message"] for e in user_errors])
            return {"success": False, "message": error_msg}
        
        # Update local store record
        await self._update_store_subscription(
            shop=shop,
            subscription_id=subscription_id,
            status="cancelled",
            plan_key=None
        )
        
        print(f"✅ [Billing] Cancelled subscription for {shop}")
        
        return {"success": True, "message": "Subscription cancelled"}
    
    async def handle_subscription_update(self, shop: str, subscription_data: Dict[str, Any]) -> None:
        """
        Handle APP_SUBSCRIPTIONS_UPDATE webhook
        
        Args:
            shop: The shop domain
            subscription_data: Webhook payload
        """
        subscription_id = subscription_data.get("app_subscription", {}).get("admin_graphql_api_id")
        status = subscription_data.get("app_subscription", {}).get("status", "").lower()
        
        print(f"📬 [Billing] Subscription update for {shop}: {status}")
        
        # Refresh subscription status from API to get full details
        await self.get_subscription_status(shop)
    
    def _determine_plan_from_subscription(self, subscription: Dict[str, Any]) -> Optional[str]:
        """Determine plan key from subscription details"""
        name = subscription.get("name", "").lower()
        
        if "professional" in name:
            return "professional"
        elif "standard" in name:
            return "standard"
        
        # Fallback: check price
        try:
            line_items = subscription.get("lineItems", [])
            if line_items:
                pricing = line_items[0].get("plan", {}).get("pricingDetails", {})
                amount = float(pricing.get("price", {}).get("amount", 0))
                if amount >= 69:
                    return "professional"
                elif amount >= 29:
                    return "standard"
        except:
            pass
        
        return "standard"  # Default
    
    async def _get_store(self, shop: str) -> Optional[Store]:
        """Get store by domain"""
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
        if not shop.endswith(".myshopify.com"):
            shop = f"{shop}.myshopify.com"
        
        result = await self.db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        return result.scalar_one_or_none()
    
    async def _update_store_subscription(
        self, 
        shop: str, 
        subscription_id: Optional[str],
        status: str,
        plan_key: Optional[str]
    ) -> None:
        """Update store's subscription info in database"""
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
        if not shop.endswith(".myshopify.com"):
            shop = f"{shop}.myshopify.com"
        
        update_data = {
            "subscription_id": subscription_id,
            "subscription_status": status,
            "updated_at": datetime.utcnow()
        }
        
        if plan_key:
            update_data["sherlock_plan"] = plan_key
        
        await self.db.execute(
            update(Store)
            .where(Store.shopify_domain == shop)
            .values(**update_data)
        )
        await self.db.commit()
    
    async def _graphql_request(
        self, 
        shop: str, 
        access_token: str, 
        query: str, 
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make a GraphQL request to Shopify Admin API"""
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
        if not shop.endswith(".myshopify.com"):
            shop = f"{shop}.myshopify.com"
        
        url = f"https://{shop}/admin/api/2024-10/graphql.json"
        
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": access_token
        }
        
        payload = {
            "query": query,
            "variables": variables
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code != 200:
                print(f"❌ [Billing] GraphQL request failed: {response.status_code} - {response.text}")
                raise Exception(f"GraphQL request failed: {response.status_code}")
            
            return response.json()


# Singleton-ish access for simple cases
billing_service = None

def get_billing_service(db: AsyncSession) -> BillingService:
    return BillingService(db)