"""add food location master

Revision ID: a1b2c3d4e5f6
Revises: 8f31b2e1c9d4
Create Date: 2026-10-23 10:35:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '8f31b2e1c9d4'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'gh_food_locations' not in inspector.get_table_names():
        op.create_table(
            'gh_food_locations',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=150), nullable=False),
            sa.Column('category', sa.String(length=100), server_default='Plant Canteen', nullable=False),
            sa.Column('description', sa.String(length=255), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_gh_food_locations'))
        )


def downgrade():
    op.drop_table('gh_food_locations')

