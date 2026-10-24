"""add arrangement_version to gh_requests

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-10-24 10:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c7d8e9f0a1b2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = [c['name'] for c in inspector.get_columns('gh_requests')]
    if 'arrangement_version' not in cols:
        op.add_column('gh_requests', sa.Column('arrangement_version', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('gh_requests', 'arrangement_version')

