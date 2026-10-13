#!/usr/bin/env python
"""
Employee Synchronization CLI Script
Syncs employees from MS SQL Server (Mantra) into Docket database.

Usage:
    python sync_employees.py                # Syncs both Staff and Associates
    python sync_employees.py --active-only  # Syncs only Active employees
    python sync_employees.py --staff-only   # Syncs only Staff records
    python sync_employees.py --assoc-only   # Syncs only Associates records
    python sync_employees.py --deactivate-missing # Mark missing employees as Inactive
"""
import argparse
import sys
import time

from app import create_app
from core import sync
from core.db import db


def sync_employees(include_staff=True, include_associates=True, active_only=False, deactivate_missing=False):
    app = create_app()
    with app.app_context():
        odbc = app.config.get("SOURCE_ODBC")
        if not odbc:
            return {
                "success": False,
                "errors": ["SOURCE_ODBC is not configured in .env. Please set SOURCE_ODBC and install pyodbc."],
                "staff_fetched": 0,
                "associates_fetched": 0,
                "total_upserted": 0,
                "duration_seconds": 0,
            }

        start_time = time.time()
        staff_fetched = 0
        associates_fetched = 0
        records = []

        views = dict(app.config.get("SOURCE_VIEWS", {}))
        if include_staff and not include_associates:
            views = {k: v for k, v in views.items() if v == "staff"}
        elif include_associates and not include_staff:
            views = {k: v for k, v in views.items() if v == "associates"}
        elif not include_staff and not include_associates:
            views = {}

        try:
            for view, source in views.items():
                header, rows = sync.fetch_view(odbc, view, active_only=active_only)
                if source == "staff":
                    staff_fetched = len(rows)
                elif source == "associates":
                    associates_fetched = len(rows)
                records += sync.normalize(header, rows, source)

            records.sort(key=lambda r: sync.SOURCE_PRIORITY.get(r["source"], 9), reverse=True)
            stats = sync.upsert(records, deactivate_missing=deactivate_missing)
            db.session.commit()
            duration = round(time.time() - start_time, 2)
            total_upserted = stats["inserted"] + stats["updated"]

            return {
                "success": True,
                "errors": [],
                "staff_fetched": staff_fetched,
                "associates_fetched": associates_fetched,
                "total_upserted": total_upserted,
                "duration_seconds": duration,
                "stats": stats,
            }
        except Exception as e:
            db.session.rollback()
            return {
                "success": False,
                "errors": [str(e)],
                "staff_fetched": staff_fetched,
                "associates_fetched": associates_fetched,
                "total_upserted": 0,
                "duration_seconds": round(time.time() - start_time, 2),
            }


def main():
    parser = argparse.ArgumentParser(description="Sync employees from SQL Server to Docket database.")
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Sync only employees with status 'Active'",
    )
    parser.add_argument(
        "--staff-only",
        action="store_true",
        help="Sync only Staff records",
    )
    parser.add_argument(
        "--assoc-only",
        action="store_true",
        help="Sync only Associates records",
    )
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="Mark employees missing from the feed as Inactive",
    )

    args = parser.parse_args()

    if args.staff_only:
        include_staff = True
        include_associates = False
    elif args.assoc_only:
        include_staff = False
        include_associates = True
    else:
        include_staff = True
        include_associates = True

    print("=" * 65)
    print("  DOCKET - EMPLOYEE MASTER SYNCHRONIZATION")
    print("=" * 65)
    print(f"  Filter:  {'Active Only' if args.active_only else 'All Statuses'}")
    print(f"  Sources: {'Staff ' if include_staff else ''}{'Associates' if include_associates else ''}")
    print("-" * 65)

    result = sync_employees(
        include_staff=include_staff,
        include_associates=include_associates,
        active_only=args.active_only,
        deactivate_missing=args.deactivate_missing,
    )

    print("-" * 65)
    if result["success"]:
        stats = result.get("stats", {})
        total_kept = stats.get("kept_manual", 0) + stats.get("kept_staff", 0)
        print("  Status: SUCCESS")
        print(f"  Staff records fetched:      {result['staff_fetched']}")
        print(f"  Associates records fetched: {result['associates_fetched']}")
        print(f"  Newly added (inserted):     {stats.get('inserted', 0)}")
        print(f"  Existing updated:           {stats.get('updated', 0)}")
        print(f"  Preserved (manual / staff): {total_kept}")
        print(f"  Managers linked:            {stats.get('managers_linked', 0)}")
        if stats.get("deactivated"):
            print(f"  Deactivated:                {stats.get('deactivated', 0)}")
        print(f"  Duration:                   {result['duration_seconds']}s")
    else:
        print("  Status: FAILED / PARTIAL")
        for err in result["errors"]:
            print(f"  Error: {err}")
        sys.exit(1)
    print("=" * 65)


if __name__ == "__main__":
    main()
