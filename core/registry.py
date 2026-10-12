"""Apps are code: each package in modules/ exposes APP = AppDef(...) and is mounted at /apps/<code>."""
import importlib
import json
import pkgutil
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.db import db

# Every app gets these. Apps add their own (e.g. guest house adds "desk").
CORE_PERMISSIONS = {
    "use": "Use the app (raise requests)",
    "masters": "Manage masters",
    "reports": "View dashboard & reports",
    "admin": "Application admin (everything in this app, incl. its configuration)",
}

# Settings every app has, before its own.
CORE_SETTINGS = {
    "enabled": {"label": "App is live", "type": "bool", "default": True,
                "help": "When off, only admins can open it."},
}


@dataclass
class AppDef:
    code: str
    name: str
    blueprint: object
    icon: str = "app"  # an icon name from core/templates/_icons.html
    description: str = ""
    home_endpoint: str = ""
    permissions: dict = field(default_factory=dict)
    # key -> {"label", "type": bool|int|text|choice, "default", "help", "choices"}
    settings: dict = field(default_factory=dict)
    # flags an approval step can be conditioned on; the record's approval_context() supplies them
    conditions: dict = field(default_factory=dict)
    # ref_id -> record exposing approval_title, approval_url, applicant, approval_context()
    approval_record: Optional[Callable] = None
    # (ref_id, outcome, actor, remarks) -> None ; outcome is approved / rejected / returned
    on_approval: Optional[Callable] = None
    # employee -> int, the red count on the home tile
    badge: Optional[Callable] = None
    # employee -> records they raised (approval_title, status, status_label, approval_endpoint/args, updated_at)
    user_requests: Optional[Callable] = None

    @property
    def all_permissions(self):
        perms = {"use": CORE_PERMISSIONS["use"], **self.permissions}
        perms.update({k: v for k, v in CORE_PERMISSIONS.items() if k != "use"})
        return perms

    @property
    def all_settings(self):
        return {**CORE_SETTINGS, **self.settings}


APPS: dict[str, AppDef] = {}


def discover(flask_app):
    import modules
    for info in pkgutil.iter_modules(modules.__path__):
        mod = importlib.import_module(f"modules.{info.name}")
        appdef = getattr(mod, "APP", None)
        if appdef is None:
            continue
        APPS[appdef.code] = appdef
        flask_app.register_blueprint(appdef.blueprint, url_prefix=f"/apps/{appdef.code}")


def get_setting(app_code, key):
    from core.models import AppSetting
    row = db.session.get(AppSetting, (app_code, key))
    if row is not None:
        return row.data
    return APPS[app_code].all_settings[key]["default"]


def set_setting(app_code, key, value):
    from core.models import AppSetting
    row = db.session.get(AppSetting, (app_code, key)) or AppSetting(app_code=app_code, key=key)
    row.value = json.dumps(value)
    db.session.add(row)
