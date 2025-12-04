"""
Sherlock - Shopify Authentication Service
Handles OAuth flow, access tokens, and session management
"""

import hmac
import hashlib
import secrets
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import urlencode, parse_qs
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import httpx

from app.core.config import settings
from app.db.models import Store


class ShopifyAuthService:
    """Service for handling Shopify OAuth authentication"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    def generate_install_url(self, shop: str, redirect_uri: str, state: Optional[str] = None) -> str:
        """
        Generate the Shopify OAuth install URL
        
        Args:
            shop: The shop domain (e.g., my-store.myshopify.com)
            redirect_uri: Where Shopify should redirect after auth
            state: Optional state parameter for CSRF protection
        
        Returns:
            The full OAuth authorization URL
        """
        if not state:
            state = secrets.token_urlsafe(32)
        
        # Ensure shop is properly formatted
        shop = self._normalize_shop_domain(shop)
        
        params = {
            "client_id": settings.shopify_api_key,
            "scope": settings.shopify_scopes,
            "redirect_uri": redirect_uri,
            "state": state,
            "grant_options[]": "per-user",  # Optional: for online access tokens
        }
        
        install_url = f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"
        
        return install_url, state
    
    async def exchange_code_for_token(self, shop: str, code: str) -> Dict[str, Any]:
        """
        Exchange the authorization code for an access token
        
        Args:
            shop: The shop domain
            code: The authorization code from Shopify
        
        Returns:
            Dict containing access_token and scope
        """
        shop = self._normalize_shop_domain(shop)
        
        token_url = f"https://{shop}/admin/oauth/access_token"
        
        payload = {
            "client_id": settings.shopify_api_key,
            "client_secret": settings.shopify_api_secret,
            "code": code,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30.0
            )
            
            if response.status_code != 200:
                print(f"❌ [Auth] Token exchange failed: {response.status_code} - {response.text}")
                raise Exception(f"Failed to exchange code: {response.status_code}")
            
            data = response.json()
            
            return {
                "access_token": data.get("access_token"),
                "scope": data.get("scope"),
            }
    
    async def verify_webhook(self, data: bytes, hmac_header: str) -> bool:
        """
        Verify that a webhook request came from Shopify
        
        Args:
            data: The raw request body
            hmac_header: The X-Shopify-Hmac-SHA256 header value
        
        Returns:
            True if valid, False otherwise
        """
        if not settings.shopify_api_secret:
            print("⚠️ [Auth] No API secret configured for webhook verification")
            return False
        
        computed_hmac = hmac.new(
            settings.shopify_api_secret.encode('utf-8'),
            data,
            hashlib.sha256
        ).digest()
        
        import base64
        computed_hmac_b64 = base64.b64encode(computed_hmac).decode('utf-8')
        
        return hmac.compare_digest(computed_hmac_b64, hmac_header)
    
    def verify_request(self, query_params: Dict[str, str]) -> bool:
        """
        Verify that an OAuth request came from Shopify
        Uses HMAC verification of query parameters
        
        Args:
            query_params: The query parameters from the request
        
        Returns:
            True if valid, False otherwise
        """
        if not settings.shopify_api_secret:
            print("⚠️ [Auth] No API secret configured")
            return False
        
        # Extract hmac from params
        hmac_value = query_params.pop("hmac", None)
        if not hmac_value:
            return False
        
        # Sort and encode remaining params
        sorted_params = sorted(query_params.items())
        encoded_params = urlencode(sorted_params)
        
        # Compute HMAC
        computed_hmac = hmac.new(
            settings.shopify_api_secret.encode('utf-8'),
            encoded_params.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(computed_hmac, hmac_value)
    
    async def store_access_token(self, shop: str, access_token: str, scope: str) -> Store:
        """
        Store or update the access token for a shop
        
        Args:
            shop: The shop domain
            access_token: The Shopify access token
            scope: The granted scopes
        
        Returns:
            The Store object
        """
        shop = self._normalize_shop_domain(shop)
        
        # Check if store exists
        result = await self.db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if store:
            # Update existing store
            store.access_token = access_token
            store.is_active = True
            store.updated_at = datetime.utcnow()
        else:
            # Create new store
            store = Store(
                shopify_domain=shop,
                access_token=access_token,
                is_active=True,
                installed_at=datetime.utcnow()
            )
            self.db.add(store)
        
        await self.db.flush()
        
        # Fetch shop info from Shopify
        await self._fetch_and_update_shop_info(store)
        
        return store
    
    async def _fetch_and_update_shop_info(self, store: Store) -> None:
        """Fetch shop details from Shopify and update store record"""
        if not store.access_token:
            return
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://{store.shopify_domain}/admin/api/2024-01/shop.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    shop_data = response.json().get("shop", {})
                    store.shop_name = shop_data.get("name")
                    store.email = shop_data.get("email")
                    store.plan_name = shop_data.get("plan_name")
                    await self.db.flush()
                    print(f"✅ [Auth] Updated shop info for {store.shopify_domain}")
        except Exception as e:
            print(f"⚠️ [Auth] Could not fetch shop info: {e}")
    
    async def revoke_access_token(self, shop: str) -> bool:
        """
        Revoke access token and mark store as inactive
        Called when app is uninstalled
        
        Args:
            shop: The shop domain
        
        Returns:
            True if successful
        """
        shop = self._normalize_shop_domain(shop)
        
        result = await self.db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        store = result.scalar_one_or_none()
        
        if store:
            # Revoke token with Shopify (optional but good practice)
            if store.access_token:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.delete(
                            f"https://{shop}/admin/api_permissions/current.json",
                            headers={
                                "X-Shopify-Access-Token": store.access_token,
                            },
                            timeout=10.0
                        )
                except:
                    pass  # Token revocation is best effort
            
            # Mark as inactive
            store.access_token = None
            store.is_active = False
            store.updated_at = datetime.utcnow()
            await self.db.flush()
            
            print(f"👋 [Auth] Revoked access for {shop}")
            return True
        
        return False
    
    async def get_store_by_domain(self, shop: str) -> Optional[Store]:
        """Get store by domain"""
        shop = self._normalize_shop_domain(shop)
        
        result = await self.db.execute(
            select(Store).where(Store.shopify_domain == shop)
        )
        return result.scalar_one_or_none()
    
    async def is_store_installed(self, shop: str) -> bool:
        """Check if a store has the app installed and active"""
        store = await self.get_store_by_domain(shop)
        return store is not None and store.is_active and store.access_token is not None
    
    def _normalize_shop_domain(self, shop: str) -> str:
        """
        Normalize shop domain to consistent format
        Handles: my-store, my-store.myshopify.com, https://my-store.myshopify.com
        """
        # Remove protocol
        shop = shop.replace("https://", "").replace("http://", "")
        
        # Remove trailing slash
        shop = shop.rstrip("/")
        
        # Add .myshopify.com if missing
        if not shop.endswith(".myshopify.com"):
            shop = f"{shop}.myshopify.com"
        
        return shop.lower()
    
    def generate_nonce(self) -> str:
        """Generate a secure random nonce for state parameter"""
        return secrets.token_urlsafe(32)
