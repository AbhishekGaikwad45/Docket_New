# Docket (new)

Flask + SQLAlchemy + Alembic + SQLite. A platform with the employee master and hierarchy, plus apps that are written as code in `modules/`.

## Run
```
pip install -r requirements.txt
copy .env.example .env          # set SECRET_KEY; OTP_SHOW_ON_SCREEN=true for local dev
alembic upgrade head
flask --app app seed-demo       # optional demo data; admin / admin123
flask --app app create-admin    # real super admin
flask --app app run
pytest -q
```

## Layout
- `core/` is the platform: employees and sync, app access grants, app settings, the approval engine (one approval org chart per app), notifications, and the activity log.
- `modules/<app>/` holds one app with its own `models.py`, `views.py` and `templates/<app>/`. `__init__.py` exposes `APP = AppDef(...)`, which declares the app's extra permissions, settings, approval conditions and hooks. The app is mounted automatically at `/apps/<code>`.
- `migrations/` is a single Alembic history for everything. After adding models: `alembic revision --autogenerate -m "..."`, then `alembic upgrade head`.

## Adding an app
Copy `modules/guest_house`, then change the code, models and views. Add an icon branch in `core/templates/_icons.html` and generate a migration. Then configure the app in Administration → Applications: who can use it, the app admins, master managers, report viewers, the approval chain and the settings.
