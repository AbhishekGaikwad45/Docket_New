"""Platform tables shared by every app: people, hierarchy, app access, approvals, activity."""
import json
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from core.db import db


approval_node_members = db.Table(
    "approval_node_members",
    db.Column("node_id", db.Integer, db.ForeignKey("approval_nodes.id", ondelete="CASCADE"), primary_key=True),
    db.Column("employee_id", db.String(50), db.ForeignKey("employees.employee_id", ondelete="CASCADE"), primary_key=True),
)


class Employee(db.Model):
    __tablename__ = "employees"

    employee_id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    designation = db.Column(db.String(150))
    department = db.Column(db.String(150), index=True)
    email = db.Column(db.String(150), index=True)
    phone = db.Column(db.String(50))
    gender = db.Column(db.String(20))
    category = db.Column(db.String(150))
    status = db.Column(db.String(30), default="Active", nullable=False, index=True)
    source = db.Column(db.String(30), default="manual", nullable=False)  # staff / associates / upload / manual

    reporting_manager_id = db.Column(db.String(50), db.ForeignKey("employees.employee_id", ondelete="SET NULL"))
    # Set when an admin edits the manager by hand, so the next sync won't overwrite it.
    manager_locked = db.Column(db.Boolean, default=False, nullable=False)

    password_hash = db.Column(db.String(255))  # only for local accounts (super admins)
    is_superadmin = db.Column(db.Boolean, default=False, nullable=False)

    last_synced_at = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    manager = db.relationship("Employee", remote_side=[employee_id])

    @property
    def is_active(self):
        return (self.status or "").lower() == "active"

    @property
    def initials(self):
        parts = [p for p in (self.name or "?").split() if p[:1].isalpha()]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @property
    def label(self):
        return f"{self.name} ({self.employee_id})"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return bool(self.password_hash) and check_password_hash(self.password_hash, password)

    def to_brief(self):
        return {
            "id": self.employee_id, "name": self.name, "designation": self.designation or "",
            "department": self.department or "", "email": self.email or "",
        }


def departments():
    """Department names, straight from the employee master."""
    rows = db.session.query(Employee.department).filter(Employee.department.isnot(None)).distinct()
    return sorted(d for (d,) in rows if d)


class AppGrant(db.Model):
    """Who holds a permission in an app. subject_type: all / department / employee."""
    __tablename__ = "app_grants"
    __table_args__ = (db.UniqueConstraint("app_code", "permission", "subject_type", "subject_value"),)

    id = db.Column(db.Integer, primary_key=True)
    app_code = db.Column(db.String(50), nullable=False, index=True)
    permission = db.Column(db.String(50), nullable=False)
    subject_type = db.Column(db.String(20), nullable=False)
    subject_value = db.Column(db.String(150), default="", nullable=False)

    def matches(self, emp):
        return {
            "all": True,
            "department": emp.department == self.subject_value,
            "employee": emp.employee_id == self.subject_value,
        }.get(self.subject_type, False)


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    app_code = db.Column(db.String(50), primary_key=True)
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text)  # JSON

    @property
    def data(self):
        return json.loads(self.value) if self.value is not None else None


class ApprovalNode(db.Model):
    """One box in an app's approval org chart. Requests climb from an entry box up to the top."""
    __tablename__ = "approval_nodes"

    id = db.Column(db.Integer, primary_key=True)
    app_code = db.Column(db.String(50), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("approval_nodes.id", ondelete="CASCADE"))
    position = db.Column(db.Integer, nullable=False, default=0)  # order among siblings
    label = db.Column(db.String(150), nullable=False)
    # Requests from these departments (newline separated) start here; entry_all = everyone not matched elsewhere.
    entry_departments = db.Column(db.Text, default="", nullable=False)
    entry_all = db.Column(db.Boolean, default=False, nullable=False)
    condition = db.Column(db.String(80), default="", nullable=False)  # app flag; level applies only when true

    parent = db.relationship("ApprovalNode", remote_side=[id], backref=db.backref(
        "children", order_by="ApprovalNode.position", cascade="all"))
    members = db.relationship("Employee", secondary=approval_node_members, order_by="Employee.name")

    @property
    def entry_list(self):
        return [d for d in self.entry_departments.split("\n") if d]

    @property
    def depth(self):
        n, node, seen = 0, self.parent, set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            n, node = n + 1, node.parent
        return n


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (db.Index("ix_notifications_unread", "employee_id", "read_at"),)

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), db.ForeignKey("employees.employee_id", ondelete="CASCADE"), nullable=False)
    app_code = db.Column(db.String(50), nullable=False)
    ref_id = db.Column(db.Integer)
    kind = db.Column(db.String(20), default="update", nullable=False)  # action (needs you) / update (FYI)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, default="")
    url = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    read_at = db.Column(db.DateTime)


class ApprovalTask(db.Model):
    """A step instantiated for one record. Approvers are snapshotted at submission time."""
    __tablename__ = "approval_tasks"
    __table_args__ = (db.Index("ix_approval_tasks_ref", "app_code", "ref_id"),)

    id = db.Column(db.Integer, primary_key=True)
    app_code = db.Column(db.String(50), nullable=False)
    ref_id = db.Column(db.Integer, nullable=False)
    round = db.Column(db.Integer, nullable=False, default=1)  # bumps on every resubmission
    position = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(150), nullable=False)
    candidates = db.Column(db.Text, default=",", nullable=False)  # ",id1,id2," - LIKE-searchable
    status = db.Column(db.String(20), nullable=False, index=True)  # waiting/pending/approved/rejected/returned/skipped/cancelled
    note = db.Column(db.String(255), default="")
    remarks = db.Column(db.Text, default="")
    acted_by_id = db.Column(db.String(50), db.ForeignKey("employees.employee_id", ondelete="SET NULL"))
    activated_at = db.Column(db.DateTime)
    acted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    acted_by = db.relationship("Employee")

    @property
    def candidate_ids(self):
        return [c for c in self.candidates.split(",") if c]

    @property
    def candidate_people(self):
        ids = self.candidate_ids
        return Employee.query.filter(Employee.employee_id.in_(ids)).all() if ids else []


class Activity(db.Model):
    """Audit trail per record: who did what, when."""
    __tablename__ = "activities"
    __table_args__ = (db.Index("ix_activities_ref", "app_code", "ref_id"),)

    id = db.Column(db.Integer, primary_key=True)
    app_code = db.Column(db.String(50), nullable=False)
    ref_id = db.Column(db.Integer, nullable=False)
    actor_id = db.Column(db.String(50), db.ForeignKey("employees.employee_id", ondelete="SET NULL"))
    action = db.Column(db.String(80), nullable=False)
    note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    actor = db.relationship("Employee")


def log_activity(app_code, ref_id, actor, action, note=""):
    db.session.add(Activity(app_code=app_code, ref_id=ref_id, actor_id=actor.employee_id if actor else None,
                            action=action, note=note))
