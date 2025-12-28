"""Add category fields to installed_apps

Revision ID: add_app_category
Revises: 
Create Date: 2025-12-28

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_app_category'
down_revision = '9b40d94abb56'
branch_labels = None
depends_on = None


def upgrade():
    # Add category column with default value
    op.add_column('installed_apps', sa.Column('category', sa.String(50), server_default='Unknown', nullable=True))
    op.add_column('installed_apps', sa.Column('category_reason', sa.String(255), nullable=True))


def downgrade():
    op.drop_column('installed_apps', 'category')
    op.drop_column('installed_apps', 'category_reason')