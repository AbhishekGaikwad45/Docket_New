"""Alembic env: one migration history for the platform and every app in modules/.
New app? Add its models, then: alembic revision --autogenerate -m "add <app>" && alembic upgrade head
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app  # noqa: E402  (imports every module, so all models are registered)
from core.db import db  # noqa: E402

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

flask_app = create_app()
target_metadata = db.metadata


def run():
    with flask_app.app_context():
        if context.is_offline_mode():
            context.configure(url=flask_app.config["SQLALCHEMY_DATABASE_URI"], target_metadata=target_metadata,
                              literal_binds=True, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
            return
        with db.engine.connect() as conn:
            # render_as_batch: SQLite can't ALTER most things, Alembic rebuilds the table instead
            context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True,
                              compare_type=True)
            with context.begin_transaction():
                context.run_migrations()


run()
