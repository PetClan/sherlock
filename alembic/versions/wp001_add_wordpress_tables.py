"""Add WordPress platform tables

Revision ID: wp001_add_wordpress_tables
Revises: ae32cd163dad
Create Date: 2025-02-25

Adds tables for WordPress site management, scan submissions,
plugin events, and plugin signatures (cross-platform learning).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'wp001_add_wordpress_tables'
down_revision = 'add_subscription_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WordPress Sites
    op.create_table(
        'wp_sites',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('site_url', sa.String(500), unique=True, nullable=False),
        sa.Column('site_name', sa.String(255), nullable=True),
        sa.Column('api_key', sa.String(255), nullable=True),
        sa.Column('license_key', sa.String(255), nullable=True),
        sa.Column('wp_version', sa.String(20), nullable=True),
        sa.Column('php_version', sa.String(20), nullable=True),
        sa.Column('active_theme', sa.String(255), nullable=True),
        sa.Column('active_plugins_count', sa.Integer, default=0),
        sa.Column('plan', sa.String(20), default='free'),
        sa.Column('plan_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('last_checkin_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('registered_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_wp_sites_url', 'wp_sites', ['site_url'])
    op.create_index('idx_wp_sites_api_key', 'wp_sites', ['api_key'])

    # WordPress Scan Submissions
    op.create_table(
        'wp_scan_submissions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('site_id', sa.String(36), sa.ForeignKey('wp_sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scan_type', sa.String(50), nullable=False),
        sa.Column('scan_source', sa.String(20), default='automated'),
        sa.Column('issues_found', sa.Integer, default=0),
        sa.Column('critical_count', sa.Integer, default=0),
        sa.Column('warning_count', sa.Integer, default=0),
        sa.Column('info_count', sa.Integer, default=0),
        sa.Column('results', sa.JSON, nullable=True),
        sa.Column('active_plugins', sa.JSON, nullable=True),
        sa.Column('active_theme', sa.String(255), nullable=True),
        sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_wp_scans_site', 'wp_scan_submissions', ['site_id'])
    op.create_index('idx_wp_scans_type', 'wp_scan_submissions', ['site_id', 'scan_type'])
    op.create_index('idx_wp_scans_date', 'wp_scan_submissions', ['scanned_at'])

    # WordPress Plugin Events
    op.create_table(
        'wp_plugin_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('site_id', sa.String(36), sa.ForeignKey('wp_sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plugin_slug', sa.String(255), nullable=False),
        sa.Column('plugin_name', sa.String(300), nullable=True),
        sa.Column('plugin_version', sa.String(50), nullable=True),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('event_details', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_wp_events_site', 'wp_plugin_events', ['site_id'])
    op.create_index('idx_wp_events_plugin', 'wp_plugin_events', ['plugin_slug'])
    op.create_index('idx_wp_events_type', 'wp_plugin_events', ['event_type'])

    # WordPress Plugin Signatures (cross-platform learning)
    op.create_table(
        'wp_plugin_signatures',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('plugin_slug', sa.String(255), unique=True, nullable=False),
        sa.Column('plugin_name', sa.String(300), nullable=True),
        sa.Column('known_css_patterns', sa.JSON, nullable=True),
        sa.Column('known_script_domains', sa.JSON, nullable=True),
        sa.Column('known_theme_modifications', sa.JSON, nullable=True),
        sa.Column('avg_risk_score', sa.Float, default=0.0),
        sa.Column('conflict_frequency', sa.Float, default=0.0),
        sa.Column('times_reported', sa.Integer, default=0),
        sa.Column('sites_seen', sa.Integer, default=0),
        sa.Column('reddit_sentiment', sa.String(50), nullable=True),
        sa.Column('reddit_risk_score', sa.Float, nullable=True),
        sa.Column('google_sentiment', sa.String(50), nullable=True),
        sa.Column('last_intel_update', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_seen', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_seen', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_wp_sig_slug', 'wp_plugin_signatures', ['plugin_slug'])
    op.create_index('idx_wp_sig_risk', 'wp_plugin_signatures', ['avg_risk_score'])
    op.create_index('idx_wp_sig_conflicts', 'wp_plugin_signatures', ['conflict_frequency'])


def downgrade() -> None:
    op.drop_table('wp_plugin_signatures')
    op.drop_table('wp_plugin_events')
    op.drop_table('wp_scan_submissions')
    op.drop_table('wp_sites')
