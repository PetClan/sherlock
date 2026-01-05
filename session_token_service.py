"""
Sherlock - Session Token Service
Handles Shopify App Bridge session token verification
"""

import jwt
import time
import base64
from typing import Optional, Dict
from app.core.config import settings


class SessionTokenService:
    """
    Service for verifying Shopify App Bridge session tokens.
    
    Session tokens are JWTs signed by Shopify that contain:
    - iss: The shop's admin URL (e.g., https://shop.myshopify.com/admin)
    - dest: The shop's URL (e.g., https://shop.myshopify.com)
    - aud: Your app's API key
    - sub: The user ID
    - exp: Expiration timestamp
    - nbf: Not before timestamp
    - iat: Issued at timestamp
    - jti: Unique token identifier
    """
    
    def __init__(self):
        self.api_key = settings.shopify_api_key
        self.api_secret = settings.shopify_api_secret
    
    def verify_session_token(self, token: str) -> Optional[Dict]:
        """
        Verify a Shopify session token.
        
        Args:
            token: The JWT session token from App Bridge
            
        Returns:
            Decoded token payload if valid, None if invalid
        """
        if not token:
            return None
        
        try:
            # Decode and verify the JWT
            # Shopify signs tokens with the app's API secret
            decoded = jwt.decode(
                token,
                self.api_secret,
                algorithms=["HS256"],
                audience=self.api_key,
                options={
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_aud": True,
                    "require": ["exp", "nbf", "iss", "dest", "aud"]
                }
            )
            
            # Extract shop domain from iss or dest
            shop_domain = self._extract_shop_domain(decoded)
            if shop_domain:
                decoded['shop'] = shop_domain
            
            return decoded
            
        except jwt.ExpiredSignatureError:
            print("⚠️ [SessionToken] Token has expired")
            return None
        except jwt.InvalidAudienceError:
            print("⚠️ [SessionToken] Invalid audience (API key mismatch)")
            return None
        except jwt.InvalidTokenError as e:
            print(f"⚠️ [SessionToken] Invalid token: {e}")
            return None
        except Exception as e:
            print(f"❌ [SessionToken] Verification error: {e}")
            return None
    
    def _extract_shop_domain(self, decoded: Dict) -> Optional[str]:
        """
        Extract the shop domain from the decoded token.
        
        Args:
            decoded: Decoded JWT payload
            
        Returns:
            Shop domain (e.g., 'my-store.myshopify.com')
        """
        # Try 'dest' first (the shop URL)
        dest = decoded.get('dest', '')
        if dest:
            # Remove https:// and trailing slash
            domain = dest.replace('https://', '').replace('http://', '').rstrip('/')
            if '.myshopify.com' in domain:
                return domain
        
        # Fallback to 'iss' (the admin URL)
        iss = decoded.get('iss', '')
        if iss:
            # Format: https://shop.myshopify.com/admin
            domain = iss.replace('https://', '').replace('http://', '').replace('/admin', '').rstrip('/')
            if '.myshopify.com' in domain:
                return domain
        
        return None
    
    def get_shop_from_token(self, token: str) -> Optional[str]:
        """
        Quick helper to extract shop domain from a session token.
        
        Args:
            token: The JWT session token
            
        Returns:
            Shop domain if valid, None if invalid
        """
        decoded = self.verify_session_token(token)
        if decoded:
            return decoded.get('shop')
        return None


# Global instance
session_token_service = SessionTokenService()