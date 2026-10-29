"""add arrival_ticket and departure_ticket to gh_guests

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-10-29 10:05:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'd8e9f0a1b2c3'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = [c['name'] for c in inspector.get_columns('gh_guests')]
    if 'arrival_ticket' not in cols:
        op.add_column('gh_guests', sa.Column('arrival_ticket', sa.String(length=255), nullable=True))
    if 'departure_ticket' not in cols:
        op.add_column('gh_guests', sa.Column('departure_ticket', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('gh_guests', 'departure_ticket')
    op.drop_column('gh_guests', 'arrival_ticket')

