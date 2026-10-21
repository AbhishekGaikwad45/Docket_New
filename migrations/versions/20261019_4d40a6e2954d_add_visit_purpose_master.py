"""add visit purpose and expense borne by masters

Revision ID: 4d40a6e2954d
Revises: a99c07a58e6a
Create Date: 2026-10-19 11:25:39.832034
"""
from alembic import op
import sqlalchemy as sa


revision = '4d40a6e2954d'
down_revision = 'a99c07a58e6a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('gh_visit_purposes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gh_visit_purposes')),
    sa.UniqueConstraint('name', name=op.f('uq_gh_visit_purposes_name'))
    )

    op.create_table('gh_expense_borne_by',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gh_expense_borne_by')),
    sa.UniqueConstraint('name', name=op.f('uq_gh_expense_borne_by_name'))
    )


def downgrade():
    op.drop_table('gh_expense_borne_by')
    op.drop_table('gh_visit_purposes')


