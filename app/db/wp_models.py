"""
Sherlock - WordPress Database Models
Models for WordPress sites, plugin intelligence, and scan submissions.
"""

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from uuid import uuid4
from datetime import datetime

from app.db.database import Base


def generate_uuid():
    return str(uuid4())


class WordPressSite(Base):
    """WordPress site registered with Sherlock"""
    __tablename__ = "wp_sites"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    site_url = Column(String(500), unique=True, nullable=False, index=True)
    site_name = Column(String(255), nullable=True)

    # API authentication
    api_key = Column(String(255), nullable=True)  # Unique key per site for auth
    license_key = Column(String(255), nullable=True)

    # WordPress environment info
    wp_version = Column(String(20), nullable=True)
    php_version = Column(String(20), nullable=True)
    active_theme = Column(String(255), nullable=True)
    active_plugins_count = Column(Integer, default=0)

    # Plan & billing
    plan = Column(String(20), default="free")  # free, standard, professional
    plan_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Status
    is_active = Column(Boolean, default=True)
    last_checkin_at = Column(DateTime(timezone=True), nullable=True)  # Last time plugin phoned home

    # Timestamps
    registered_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    scan_submissions = relationship("WPScanSubmission", back_populates="site", cascade="all, delete-orphan")
    plugin_events = relationship("WPPluginEvent", back_populates="site", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_wp_sites_url", "site_url"),
        Index("idx_wp_sites_api_key", "api_key"),
    )


class WPScanSubmission(Base):
    """Scan results submitted from WordPress plugin instances"""
    __tablename__ = "wp_scan_submissions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    site_id = Column(String(36), ForeignKey("wp_sites.id", ondelete="CASCADE"), nullable=False)

    # Scan metadata
    scan_type = Column(String(50), nullable=False)  # theme_monitor, plugin_conflict, css_risk
    scan_source = Column(String(20), default="automated")  # automated, manual

    # Results summary
    issues_found = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    info_count = Column(Integer, default=0)

    # Full results
    results = Column(JSON, nullable=True)  # Complete scan results from the plugin
    active_plugins = Column(JSON, nullable=True)  # List of active plugin slugs at scan time
    active_theme = Column(String(255), nullable=True)

    # Timestamps
    scanned_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    site = relationship("WordPressSite", back_populates="scan_submissions")

    __table_args__ = (
        Index("idx_wp_scans_site", "site_id"),
        Index("idx_wp_scans_type", "site_id", "scan_type"),
        Index("idx_wp_scans_date", "scanned_at"),
    )


class WPPluginEvent(Base):
    """Plugin events reported from WordPress sites (for signature learning)"""
    __tablename__ = "wp_plugin_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    site_id = Column(String(36), ForeignKey("wp_sites.id", ondelete="CASCADE"), nullable=False)

    # Plugin info
    plugin_slug = Column(String(255), nullable=False)
    plugin_name = Column(String(300), nullable=True)
    plugin_version = Column(String(50), nullable=True)

    # Event
    event_type = Column(String(50), nullable=False)  # activated, deactivated, updated, theme_switched
    event_details = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    site = relationship("WordPressSite", back_populates="plugin_events")

    __table_args__ = (
        Index("idx_wp_events_site", "site_id"),
        Index("idx_wp_events_plugin", "plugin_slug"),
        Index("idx_wp_events_type", "event_type"),
    )


class WPPluginSignature(Base):
    """
    Learned WordPress plugin signatures (cross-platform knowledge).
    Similar to AppSignature but for WordPress plugins.
    Shared across all WordPress sites for collective intelligence.
    """
    __tablename__ = "wp_plugin_signatures"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Plugin identification
    plugin_slug = Column(String(255), nullable=False, unique=True, index=True)
    plugin_name = Column(String(300), nullable=True)

    # Known patterns (CSS selectors, script URLs, theme modifications)
    known_css_patterns = Column(JSON, nullable=True)  # Non-namespaced CSS selectors this plugin uses
    known_script_domains = Column(JSON, nullable=True)  # External script domains loaded
    known_theme_modifications = Column(JSON, nullable=True)  # Theme files this plugin typically modifies

    # Risk profile (learned from scan submissions)
    avg_risk_score = Column(Float, default=0.0)  # Average risk score from all sites
    conflict_frequency = Column(Float, default=0.0)  # How often this plugin appears in conflict reports
    times_reported = Column(Integer, default=0)  # Number of times flagged across sites
    sites_seen = Column(Integer, default=0)  # Number of sites with this plugin

    # Intelligence cache
    reddit_sentiment = Column(String(50), nullable=True)  # positive, negative, mixed, neutral
    reddit_risk_score = Column(Float, nullable=True)
    google_sentiment = Column(String(50), nullable=True)
    last_intel_update = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_wp_sig_slug", "plugin_slug"),
        Index("idx_wp_sig_risk", "avg_risk_score"),
        Index("idx_wp_sig_conflicts", "conflict_frequency"),
    )
