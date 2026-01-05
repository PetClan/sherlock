"""Add subscription fields to stores table

Revision ID: add_subscription_fields
Revises: add_system_settings
Create Date: 2025-01-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_subscription_fields'
down_revision = 'add_system_settings'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stores', sa.Column('subscription_id', sa.String(255), nullable=True))
    op.add_column('stores', sa.Column('subscription_status', sa.String(50), nullable=True))
    op.add_column('stores', sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('stores', 'trial_ends_at')
    op.drop_column('stores', 'subscription_status')
    op.drop_column('stores', 'subscription_id')