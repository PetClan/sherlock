"""
Sherlock - Database models
"""

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from uuid import uuid4

from app.db.database import Base


def generate_uuid():
    return str(uuid4())


class Store(Base):
    """Shopify store connected to Sherlock"""
    __tablename__ = "stores"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    shopify_domain = Column(String(255), unique=True, nullable=False, index=True)
    access_token = Column(String(255), nullable=True)  # Encrypted in production
    shop_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    plan_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    installed_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    installed_apps = relationship("InstalledApp", back_populates="store", cascade="all, delete-orphan")
    diagnoses = relationship("Diagnosis", back_populates="store", cascade="all, delete-orphan")
    theme_issues = relationship("ThemeIssue", back_populates="store", cascade="all, delete-orphan")
    performance_snapshots = relationship("PerformanceSnapshot", back_populates="store", cascade="all, delete-orphan")


class InstalledApp(Base):
    """Third-party apps installed on a store"""
    __tablename__ = "installed_apps"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    store_id = Column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    
    # App identification
    app_name = Column(String(255), nullable=False)
    app_handle = Column(String(255), nullable=True)  # URL-friendly identifier
    app_id = Column(String(100), nullable=True)  # Shopify's app ID if available
    
    # Install info
    installed_on = Column(DateTime(timezone=True), nullable=True)
    last_updated = Column(String(50), nullable=True)  # From app store listing
    
    # Risk indicators
    is_suspect = Column(Boolean, default=False)  # Flagged as potential issue
    risk_score = Column(Float, default=0.0)  # 0-100 risk score
    risk_reasons = Column(JSON, nullable=True)  # List of reasons for risk score
    
    # Detection info
    injects_scripts = Column(Boolean, default=False)
    injects_theme_code = Column(Boolean, default=False)
    script_count = Column(Integer, default=0)
    
    # Timestamps
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_scanned = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    store = relationship("Store", back_populates="installed_apps")
    
    __table_args__ = (
        Index("idx_installed_apps_store", "store_id"),
        Index("idx_installed_apps_suspect", "store_id", "is_suspect"),
    )


class Diagnosis(Base):
    """Diagnosis/scan results for a store"""
    __tablename__ = "diagnoses"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    store_id = Column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    
    # Scan info
    scan_type = Column(String(50), nullable=False)  # "full", "quick", "apps_only", "theme_only", "performance"
    status = Column(String(20), default="pending")  # "pending", "running", "completed", "failed"
    
    # Results summary
    total_apps_scanned = Column(Integer, default=0)
    issues_found = Column(Integer, default=0)
    suspect_apps = Column(JSON, nullable=True)  # List of app names flagged
    
    # Performance metrics at time of scan
    load_time_ms = Column(Integer, nullable=True)
    performance_score = Column(Float, nullable=True)  # 0-100
    
    # Detailed results
    results = Column(JSON, nullable=True)  # Full scan results
    recommendations = Column(JSON, nullable=True)  # Actionable recommendations
    
    # Timestamps
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    store = relationship("Store", back_populates="diagnoses")
    
    __table_args__ = (
        Index("idx_diagnoses_store", "store_id"),
        Index("idx_diagnoses_status", "store_id", "status"),
    )


class ThemeIssue(Base):
    """Theme code conflicts/issues detected"""
    __tablename__ = "theme_issues"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    store_id = Column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    
    # Theme info
    theme_id = Column(String(50), nullable=True)
    theme_name = Column(String(255), nullable=True)
    
    # Issue details
    file_path = Column(String(255), nullable=False)  # e.g., "layout/theme.liquid"
    issue_type = Column(String(50), nullable=False)  # "injected_script", "duplicate_code", "conflict", "error"
    severity = Column(String(20), default="medium")  # "low", "medium", "high", "critical"
    
    # Code context
    line_number = Column(Integer, nullable=True)
    code_snippet = Column(Text, nullable=True)
    
    # Attribution
    likely_source = Column(String(255), nullable=True)  # App name that likely caused this
    confidence = Column(Float, default=0.0)  # 0-100 confidence in attribution
    
    # Resolution
    is_resolved = Column(Boolean, default=False)
    resolution_notes = Column(Text, nullable=True)
    
    # Timestamps
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    store = relationship("Store", back_populates="theme_issues")
    
    __table_args__ = (
        Index("idx_theme_issues_store", "store_id"),
        Index("idx_theme_issues_severity", "store_id", "severity"),
    )


class PerformanceSnapshot(Base):
    """Performance metrics snapshots over time"""
    __tablename__ = "performance_snapshots"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    store_id = Column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    
    # Core metrics
    load_time_ms = Column(Integer, nullable=True)  # Total page load time
    time_to_first_byte_ms = Column(Integer, nullable=True)
    time_to_interactive_ms = Column(Integer, nullable=True)
    
    # Scores
    performance_score = Column(Float, nullable=True)  # 0-100 (like Lighthouse)
    seo_score = Column(Float, nullable=True)
    accessibility_score = Column(Float, nullable=True)
    
    # Resource counts
    total_requests = Column(Integer, nullable=True)
    total_size_kb = Column(Float, nullable=True)
    script_count = Column(Integer, nullable=True)
    third_party_script_count = Column(Integer, nullable=True)
    
    # Slow resources
    slow_resources = Column(JSON, nullable=True)  # List of resources taking >1s
    blocking_scripts = Column(JSON, nullable=True)  # Scripts blocking render
    
    # Context
    page_tested = Column(String(50), default="homepage")  # "homepage", "product", "collection", "cart"
    tested_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    store = relationship("Store", back_populates="performance_snapshots")
    
    __table_args__ = (
        Index("idx_performance_store", "store_id"),
        Index("idx_performance_time", "store_id", "tested_at"),
    )


class ReportedApp(Base):
    """Community-reported problematic apps (global, not per-store)"""
    __tablename__ = "reported_apps"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    
    # App identification
    app_name = Column(String(255), nullable=False, index=True)
    app_handle = Column(String(255), nullable=True)  # URL-friendly name
    
    # Risk data from Reddit
    reddit_risk_score = Column(Float, default=0.0)  # 0-100
    reddit_posts_found = Column(Integer, default=0)
    reddit_sentiment = Column(String(50), nullable=True)  # positive, negative, mixed
    reddit_common_issues = Column(JSON, nullable=True)  # List of common issues
    reddit_sample_posts = Column(JSON, nullable=True)  # Sample post URLs
    
    # Report counts
    total_reports = Column(Integer, default=1)  # How many users reported this
    report_reasons = Column(JSON, nullable=True)  # Aggregated reasons
    
    # Issue types reported
    causes_slowdown = Column(Boolean, default=False)
    causes_conflicts = Column(Boolean, default=False)
    causes_checkout_issues = Column(Boolean, default=False)
    causes_theme_issues = Column(Boolean, default=False)
    poor_support = Column(Boolean, default=False)
    
    # Status
    is_verified = Column(Boolean, default=False)  # Manually verified by admin
    is_active = Column(Boolean, default=True)  # Still being reported
    
    # Timestamps
    first_reported = Column(DateTime(timezone=True), server_default=func.now())
    last_reported = Column(DateTime(timezone=True), server_default=func.now())
    last_reddit_check = Column(DateTime(timezone=True), nullable=True)
    
    __table_args__ = (
        Index("idx_reported_apps_name", "app_name"),
        Index("idx_reported_apps_risk", "reddit_risk_score"),
    )
    
