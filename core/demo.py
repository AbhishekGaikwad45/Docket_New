"""Demo data: `flask seed-demo`. Fictional people; safe to run more than once."""
from core.db import db
from core.models import AppGrant, ApprovalNode, Employee
PEOPLE = [
    # id, name, designation, department, manager
    ("1001", "Arjun Mehta", "Unit Head", "Management", None),
    ("1002", "Kavita Rao", "General Manager - HR", "HR & Admin", "1001"),
    ("1003", "Rohan Desai", "Senior Manager - Administration", "HR & Admin", "1002"),
    ("1004", "Neha Kulkarni", "Officer - Administration", "HR & Admin", "1003"),
    ("1005", "Amit Patil", "General Manager - Marine", "Marine Operations", "1001"),
    ("1006", "Sneha Joshi", "Manager - Marine", "Marine Operations", "1005"),
    ("1007", "Vikas More", "Engineer - Marine", "Marine Operations", "1006"),
    ("1008", "Farhan Shaikh", "Deputy General Manager - IT", "Information Technology", "1001"),
    ("1009", "Pooja Rane", "Executive - IT", "Information Technology", "1008"),
]


# label, members, entry departments, condition, children
CHART = ("Unit Head approval (hotel stays)", ["1001"], [], "needs_hotel", [
    ("Admin Head approval", ["1003"], [], "", [
        ("HOD - Marine Operations", ["1005"], ["Marine Operations"], "", [
            ("Manager - Marine", ["1006"], ["Marine Operations"], "", []),
        ]),
        ("HOD - Information Technology", ["1008"], ["Information Technology"], "", []),
        ("HOD - HR & Admin", ["1002"], ["HR & Admin"], "", []),
    ]),
])


def _build(spec, parent=None, position=0):
    label, members, entry, condition, children = spec
    node = ApprovalNode(app_code="guest_house", parent=parent, position=position, label=label, condition=condition,
                        entry_departments="\n".join(entry),
                        members=[db.session.get(Employee, m) for m in members])
    db.session.add(node)
    for i, child in enumerate(children):
        _build(child, node, i)


def seed():
    if Employee.query.filter(Employee.employee_id != "admin").count():
        print("Employees already exist - skipping people.")
    else:
        for emp_id, name, desig, dept, mgr in PEOPLE:
            db.session.add(Employee(employee_id=emp_id, name=name, designation=desig, department=dept,
                                    email=f"{name.split()[0].lower()}@example.com", reporting_manager_id=mgr,
                                    source="manual", status="Active"))
        db.session.flush()

    admin = db.session.get(Employee, "admin") or Employee(employee_id="admin", name="Administrator", source="manual")
    admin.is_superadmin, admin.status = True, "Active"
    if not admin.password_hash:
        admin.set_password("admin123")
    db.session.add(admin)

    for perm, kind, value in [("use", "all", ""), ("desk", "employee", "1003"), ("desk", "employee", "1004"),
                              ("masters", "employee", "1004"), ("reports", "employee", "1003"),
                              ("reports", "employee", "1001"), ("admin", "employee", "1003")]:
        if not AppGrant.query.filter_by(app_code="guest_house", permission=perm, subject_type=kind, subject_value=value).first():
            db.session.add(AppGrant(app_code="guest_house", permission=perm, subject_type=kind, subject_value=value))
    if not ApprovalNode.query.filter_by(app_code="guest_house").count():
        _build(CHART)
    from modules.guest_house.models import GuestHouse, Hotel, Room, Vehicle, VisitPurpose, ExpenseBorneBy, VISIT_TYPES, EXPENSES_BY
    if not GuestHouse.query.count():
        gh1 = GuestHouse(name="Jaigarh Guest House", location="Jaigarh", contact_phone="02357-000000")
        gh2 = GuestHouse(name="Colony Guest House", location="Port colony")
        db.session.add_all([gh1, gh2])
        for no, kind, beds in [("101", "Single", 1), ("102", "Double", 2), ("103", "Double", 2), ("104", "Suite", 2),
                               ("105", "Twin", 2), ("106", "Single", 1)]:
            db.session.add(Room(guest_house=gh1, room_no=no, room_type=kind, capacity=beds))
        for no, kind, beds in [("A1", "Double", 2), ("A2", "Double", 2), ("A3", "Dormitory", 6)]:
            db.session.add(Room(guest_house=gh2, room_no=no, room_type=kind, capacity=beds))
        db.session.add_all([
            Hotel(name="Sea View Residency", city="Ratnagiri", phone="02352-000000", tariff="Rs 4,500 + tax (CP)"),
            Hotel(name="Harbour Inn", city="Ganpatipule", phone="02357-111111", tariff="Rs 3,800 (EP)"),
            Vehicle(reg_no="MH08AB1234", model="Innova Crysta", vehicle_type="MUV", seats=7, driver_name="Suresh", driver_phone="9000000001"),
            Vehicle(reg_no="MH08CD5678", model="Dzire", vehicle_type="Sedan", seats=4, driver_name="Mahesh", driver_phone="9000000002"),
            Vehicle(reg_no="MH08EF9012", model="Tempo Traveller", vehicle_type="Tempo Traveller", seats=12, ownership="Leased"),
        ])
    if not VisitPurpose.query.count():
        for name in VISIT_TYPES:
            db.session.add(VisitPurpose(name=name))
    if not ExpenseBorneBy.query.count():
        for name in EXPENSES_BY:
            db.session.add(ExpenseBorneBy(name=name))
    db.session.commit()
