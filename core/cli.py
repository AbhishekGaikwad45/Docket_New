import click

from core import sync
from core.db import db
from core.models import Employee


def init_app(app):
    @app.cli.command("create-admin")
    @click.option("--username", default="admin")
    @click.password_option()
    def create_admin(username, password):
        """Create or reset a local super admin account."""
        emp = db.session.get(Employee, username) or Employee(employee_id=username, name="Administrator", source="manual")
        emp.is_superadmin, emp.status = True, "Active"
        emp.set_password(password)
        db.session.add(emp)
        db.session.commit()
        click.echo(f"Super admin '{username}' ready.")

    @app.cli.command("sync-employees")
    @click.option("--file", "path", help="Import an .xlsx/.csv instead of the SQL Server views.")
    @click.option("--active-only", is_flag=True)
    @click.option("--deactivate-missing", is_flag=True)
    def sync_employees(path, active_only, deactivate_missing):
        """Sync the employee master (schedule this nightly)."""
        if path:
            with open(path, "rb") as fh:
                header, rows = sync.read_file(path, fh)
            records = sync.normalize(header, rows, "upload")
        else:
            records = []
            for view, source in app.config["SOURCE_VIEWS"].items():
                header, rows = sync.fetch_view(app.config["SOURCE_ODBC"], view, active_only)
                records += sync.normalize(header, rows, source)
            records.sort(key=lambda r: sync.SOURCE_PRIORITY.get(r["source"], 9), reverse=True)
        stats = sync.upsert(records, deactivate_missing)
        db.session.commit()
        click.echo(stats)

    @app.cli.command("seed-demo")
    def seed_demo():
        """Demo people, hierarchy, app access, approval chain and guest house masters."""
        from core.demo import seed
        seed()
        click.echo("Demo data loaded. Super admin: admin / admin123. Employees sign in with OTP (set OTP_SHOW_ON_SCREEN=true).")
