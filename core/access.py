from flask import g

from core.models import AppGrant, Employee
from core.registry import APPS, get_setting


def permissions_of(emp, app_code):
    """Set of permissions emp holds in app_code (cached for the request)."""
    if emp is None:
        return set()
    cache = g.setdefault("_perm_cache", {})
    key = (emp.employee_id, app_code)
    if key not in cache:
        if emp.is_superadmin:
            perms = set(APPS[app_code].all_permissions)
        else:
            perms = {gr.permission for gr in AppGrant.query.filter_by(app_code=app_code) if gr.matches(emp)}
            if "admin" in perms:
                perms = set(APPS[app_code].all_permissions)
        cache[key] = perms
    return cache[key]


def can(emp, app_code, perm):
    return perm in permissions_of(emp, app_code)


def visible_apps(emp):
    """Apps to show on the home grid: any permission, and live (or user is its admin)."""
    out = []
    for app in APPS.values():
        perms = permissions_of(emp, app.code)
        if perms and (get_setting(app.code, "enabled") or "admin" in perms):
            out.append(app)
    return out


def holders(app_code, perm):
    """Active employees explicitly granted perm (department/employee grants; 'all' is ignored)."""
    people = {}
    for gr in AppGrant.query.filter_by(app_code=app_code, permission=perm):
        if gr.subject_type == "employee":
            found = Employee.query.filter_by(employee_id=gr.subject_value).all()
        elif gr.subject_type == "department":
            found = Employee.query.filter_by(department=gr.subject_value).all()
        else:
            found = []
        people.update({e.employee_id: e for e in found if e.is_active})
    return list(people.values())
