"""
Sherlock - Shopify App Diagnostics
Configuration settings
"""

from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # App Info
    app_name: str = "Sherlock - Shopify App Diagnostics"
    environment: str = "development"
    debug: bool = True
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./sherlock.db"
    
    # Shopify App Credentials
    shopify_api_key: str = ""
    shopify_api_secret: str = ""
    shopify_scopes: str = "read_themes,write_themes,read_products,read_script_tags,read_content"
    
    # App URL (for OAuth callback)
    app_url: str = "http://localhost:8000"
    
    # CORS
    cors_origins: str = "*"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string"""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    @property
    def shopify_scopes_list(self) -> List[str]:
        """Parse Shopify scopes from comma-separated string"""
        return [scope.strip() for scope in self.shopify_scopes.split(",")]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()
