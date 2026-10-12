import sqlite3

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine

# Named constraints so Alembic batch migrations on SQLite can drop/alter them later.
db = SQLAlchemy(metadata=MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}))


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(conn, _record):
    if isinstance(conn, sqlite3.Connection):
        conn.execute("PRAGMA foreign_keys=ON")
