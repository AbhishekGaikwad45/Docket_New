"""add airport and railway station masters

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-28 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd8e9f0a1b2c3'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'gh_airports' not in existing_tables:
        airports_table = op.create_table(
            'gh_airports',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=150), nullable=False),
            sa.Column('code', sa.String(length=20), nullable=True),
            sa.Column('city', sa.String(length=100), nullable=True),
            sa.Column('state', sa.String(length=100), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_gh_airports'))
        )
        # Seed initial airports
        initial_airports = [
            {"name": "Chhatrapati Shivaji Maharaj International Airport", "code": "BOM", "city": "Mumbai", "state": "Maharashtra", "is_active": True},
            {"name": "Indira Gandhi International Airport", "code": "DEL", "city": "New Delhi", "state": "Delhi", "is_active": True},
            {"name": "Kempegowda International Airport", "code": "BLR", "city": "Bengaluru", "state": "Karnataka", "is_active": True},
            {"name": "Rajiv Gandhi International Airport", "code": "HYD", "city": "Hyderabad", "state": "Telangana", "is_active": True},
            {"name": "Chennai International Airport", "code": "MAA", "city": "Chennai", "state": "Tamil Nadu", "is_active": True},
            {"name": "Netaji Subhash Chandra Bose International Airport", "code": "CCU", "city": "Kolkata", "state": "West Bengal", "is_active": True},
            {"name": "Pune Airport", "code": "PNQ", "city": "Pune", "state": "Maharashtra", "is_active": True},
            {"name": "Sardar Vallabhbhai Patel International Airport", "code": "AMD", "city": "Ahmedabad", "state": "Gujarat", "is_active": True},
            {"name": "Goa Dabolim Airport", "code": "GOI", "city": "Goa", "state": "Goa", "is_active": True},
            {"name": "Manohar International Airport (Mopa)", "code": "GOX", "city": "Goa", "state": "Goa", "is_active": True},
        ]
        op.bulk_insert(airports_table, initial_airports)

    if 'gh_railway_stations' not in existing_tables:
        stations_table = op.create_table(
            'gh_railway_stations',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=150), nullable=False),
            sa.Column('code', sa.String(length=20), nullable=True),
            sa.Column('city', sa.String(length=100), nullable=True),
            sa.Column('state', sa.String(length=100), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_gh_railway_stations'))
        )
        # Seed initial railway stations
        initial_stations = [
            {"name": "Mumbai CSMT", "code": "CSMT", "city": "Mumbai", "state": "Maharashtra", "is_active": True},
            {"name": "Mumbai Central", "code": "MMCT", "city": "Mumbai", "state": "Maharashtra", "is_active": True},
            {"name": "Lokmanya Tilak Terminus", "code": "LTT", "city": "Mumbai", "state": "Maharashtra", "is_active": True},
            {"name": "Panvel Junction", "code": "PNVL", "city": "Navi Mumbai", "state": "Maharashtra", "is_active": True},
            {"name": "Pune Junction", "code": "PUNE", "city": "Pune", "state": "Maharashtra", "is_active": True},
            {"name": "New Delhi", "code": "NDLS", "city": "New Delhi", "state": "Delhi", "is_active": True},
            {"name": "Hazrat Nizamuddin", "code": "NZM", "city": "Delhi", "state": "Delhi", "is_active": True},
            {"name": "Ahmedabad Junction", "code": "ADI", "city": "Ahmedabad", "state": "Gujarat", "is_active": True},
            {"name": "Howrah Junction", "code": "HWH", "city": "Kolkata", "state": "West Bengal", "is_active": True},
            {"name": "KSR Bengaluru", "code": "SBC", "city": "Bengaluru", "state": "Karnataka", "is_active": True},
            {"name": "Chennai Central", "code": "MAS", "city": "Chennai", "state": "Tamil Nadu", "is_active": True},
        ]
        op.bulk_insert(stations_table, initial_stations)


def downgrade():
    op.drop_table('gh_railway_stations')
    op.drop_table('gh_airports')

