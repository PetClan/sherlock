"""
Sherlock - Authentication Middleware
Handles session token verification for API requests
"""

from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from session_token_service import session_token_service


# Security scheme for Bearer tokens
security = HTTPBearer(auto_error=False)


async def get_current_shop(request: Request) -> str:
    """
    Dependency that extracts and verifies the shop from the request.
    
    Checks in order:
    1. Authorization header (session token) - for embedded apps
    2. Query parameter 'shop' - fallback for development/standalone
    
    Returns:
        Shop domain (e.g., 'my-store.myshopify.com')
        
    Raises:
        HTTPException: If no valid authentication found
    """
    # First, try Authorization header (session token)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        shop = session_token_service.get_shop_from_token(token)
        if shop:
            print(f"🔑 [Auth] Authenticated via session token: {shop}")
            return shop
        else:
            print("⚠️ [Auth] Invalid session token provided")
            # Don't raise here, fall through to check query param
    
    # Fallback: Check query parameter (for development/standalone mode)
    shop = request.query_params.get("shop")
    if shop:
        print(f"⚠️ [Auth] Using query param auth (standalone mode): {shop}")
        return shop
    
    # Also check if shop is in the URL path
    # e.g., /api/v1/apps/my-store.myshopify.com
    path_parts = request.url.path.split("/")
    for part in path_parts:
        if ".myshopify.com" in part:
            print(f"⚠️ [Auth] Using URL path auth: {part}")
            return part
    
    # No authentication found
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Please provide a valid session token or shop parameter."
    )


async def get_optional_shop(request: Request) -> Optional[str]:
    """
    Same as get_current_shop but returns None instead of raising exception.
    Useful for endpoints that work with or without authentication.
    """
    try:
        return await get_current_shop(request)
    except HTTPException:
        return None


async def verify_session_token(request: Request) -> dict:
    """
    Strictly verify session token from Authorization header.
    Use this for sensitive operations that require embedded auth.
    
    Returns:
        Decoded token payload
        
    Raises:
        HTTPException: If no valid session token
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Session token required. This action requires embedded app authentication."
        )
    
    token = auth_header.replace("Bearer ", "")
    decoded = session_token_service.verify_session_token(token)
    
    if not decoded:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session token. Please refresh the page."
        )
    
    return decoded