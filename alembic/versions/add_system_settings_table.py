"""Add system_settings table

Revision ID: add_system_settings
Revises: 5f5d67465784
Create Date: 2024-12-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_system_settings'
down_revision = '5f5d67465784'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'system_settings',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('key', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('value', sa.String(500), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.String(100), nullable=True),
    )


def downgrade():
    op.drop_table('system_settings')