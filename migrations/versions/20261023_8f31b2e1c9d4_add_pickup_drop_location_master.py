"""add pickup and drop location master

Revision ID: 8f31b2e1c9d4
Revises: 4d40a6e2954d
Create Date: 2026-10-23 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '8f31b2e1c9d4'
down_revision = '4d40a6e2954d'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'gh_locations' not in inspector.get_table_names():
        op.create_table(
            'gh_locations',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('point_name', sa.String(length=150), nullable=False),
            sa.Column('city', sa.String(length=100), nullable=True),
            sa.Column('state', sa.String(length=100), nullable=True),
            sa.Column('location_type', sa.String(length=50), server_default='Domestic', nullable=False),
            sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_gh_locations'))
        )


def downgrade():
    op.drop_table('gh_locations')

