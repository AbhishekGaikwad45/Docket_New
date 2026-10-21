from datetime import datetime, timedelta

from core.db import db

STATUSES = {
    "pending": "Pending approval",
    "returned": "Sent back",
    "rejected": "Rejected",
    "approved": "Approved - awaiting arrangement",
    "arranged": "Arranged",
    "completed": "Completed",
    "cancelled": "Cancelled",
}
BOOKED = ("approved", "arranged")  # only these hold rooms and vehicles
VISIT_TYPES = ["Official visit", "Audit", "Customer", "Vendor / Contractor", "Interview", "Training",
               "New joinee", "Group company", "Government / Statutory", "Other"]
EXPENSES_BY = ["Company", "Department (cost centre)", "Guest / Visitor", "Group company"]
STAY_TYPES = {"guest_house": "Guest house", "hotel": "Hotel", "none": "Not required"}
TRIP_TYPES = ["Pickup", "Drop", "Local", "Pickup & drop", "Outstation"]


class GuestHouse(db.Model):
    __tablename__ = "gh_guest_houses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    location = db.Column(db.String(150))
    address = db.Column(db.Text)
    contact_phone = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    rooms = db.relationship("Room", back_populates="guest_house", order_by="Room.room_no")

    def __str__(self):
        return self.name


class Room(db.Model):
    __tablename__ = "gh_rooms"
    __table_args__ = (db.UniqueConstraint("guest_house_id", "room_no"),)
    id = db.Column(db.Integer, primary_key=True)
    guest_house_id = db.Column(db.Integer, db.ForeignKey("gh_guest_houses.id"), nullable=False)
    room_no = db.Column(db.String(30), nullable=False)
    room_type = db.Column(db.String(30), default="Single")
    capacity = db.Column(db.Integer, default=1, nullable=False)
    amenities = db.Column(db.String(255))
    remarks = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # off = under maintenance
    guest_house = db.relationship("GuestHouse", back_populates="rooms")

    def __str__(self):
        return f"{self.guest_house.name} - {self.room_no}"


class Hotel(db.Model):
    __tablename__ = "gh_hotels"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    city = db.Column(db.String(100))
    address = db.Column(db.Text)
    contact_person = db.Column(db.String(150))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(150))
    tariff = db.Column(db.String(255))  # agreed corporate rate, free text
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __str__(self):
        return f"{self.name}, {self.city}" if self.city else self.name


class Vehicle(db.Model):
    __tablename__ = "gh_vehicles"
    id = db.Column(db.Integer, primary_key=True)
    reg_no = db.Column(db.String(30), unique=True, nullable=False)
    model = db.Column(db.String(100))
    vehicle_type = db.Column(db.String(50))
    seats = db.Column(db.Integer, default=4)
    ownership = db.Column(db.String(30), default="Company")
    driver_name = db.Column(db.String(150))
    driver_phone = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __str__(self):
        return f"{self.reg_no} ({self.model or self.vehicle_type or 'vehicle'})"


class VisitPurpose(db.Model):
    __tablename__ = "gh_visit_purposes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __str__(self):
        return self.name


class ExpenseBorneBy(db.Model):
    __tablename__ = "gh_expense_borne_by"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __str__(self):
        return self.name


class GuestRequest(db.Model):
    __tablename__ = "gh_requests"
    id = db.Column(db.Integer, primary_key=True)
    req_no = db.Column(db.String(30), unique=True)
    applicant_id = db.Column(db.String(50), db.ForeignKey("employees.employee_id"), nullable=False, index=True)
    department = db.Column(db.String(150))  # snapshot at submission

    visit_type = db.Column(db.String(50), nullable=False)
    purpose = db.Column(db.Text, nullable=False)
    organisation = db.Column(db.String(200))
    expenses_by = db.Column(db.String(50), nullable=False, default="Company")
    cost_centre = db.Column(db.String(100))

    # What the requester asks for (yes/no + a note). The desk fills the actual arrangement.
    need_guest_house = db.Column(db.Boolean, default=False, nullable=False)
    need_hotel = db.Column(db.Boolean, default=False, nullable=False)
    need_vehicle = db.Column(db.Boolean, default=False, nullable=False)
    need_food = db.Column(db.Boolean, default=False, nullable=False)
    need_ticket = db.Column(db.Boolean, default=False, nullable=False)
    vehicle_note = db.Column(db.Text)
    food_note = db.Column(db.Text)
    ticket_note = db.Column(db.Text)
    other_note = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    submitted_at = db.Column(db.DateTime)
    decided_at = db.Column(db.DateTime)

    # Administration use
    food_arrangement = db.Column(db.Text)
    ticket_arrangement = db.Column(db.Text)
    desk_remarks = db.Column(db.Text)
    arranged_by_id = db.Column(db.String(50), db.ForeignKey("employees.employee_id"))
    arranged_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    applicant = db.relationship("Employee", foreign_keys=[applicant_id])
    arranged_by = db.relationship("Employee", foreign_keys=[arranged_by_id])
    guests = db.relationship("Guest", back_populates="request", cascade="all, delete-orphan", order_by="Guest.id")
    trips = db.relationship("Trip", back_populates="request", cascade="all, delete-orphan", order_by="Trip.start")

    # --- approval engine interface
    approval_endpoint = "guest_house.request_view"

    @property
    def approval_args(self):
        return {"req_id": self.id}

    @property
    def approval_title(self):
        n = len(self.guests)
        return f"{self.req_no} - {n} guest{'s' if n != 1 else ''} ({self.visit_type}) by {self.applicant.name}"

    def approval_context(self):
        return {
            "needs_guest_house": self.need_guest_house, "needs_hotel": self.need_hotel,
            "needs_vehicle": self.need_vehicle, "needs_ticket": self.need_ticket,
            "not_company_paid": self.expenses_by != "Company",
            "large_group": len(self.guests) > 4,
        }

    # --- helpers
    @property
    def travel_mode(self):
        if not self.ticket_note:
            return ""
        import re
        m = re.search(r"<!--TRAVEL_MODE:(.*?)-->", self.ticket_note)
        if m:
            return m.group(1).strip()
        m2 = re.match(r"^Mode:\s*([^|\n]+)", self.ticket_note)
        if m2:
            return m2.group(1).strip()
        return ""

    @property
    def clean_vehicle_note(self):
        if not self.vehicle_note:
            return ""
        import re
        return re.sub(r"<!--VEHICLE_DATA:.*?-->", "", self.vehicle_note, flags=re.S).strip()

    @property
    def clean_food_note(self):
        if not self.food_note:
            return ""
        import re
        return re.sub(r"<!--FOOD_DATA:.*?-->", "", self.food_note, flags=re.S).strip()

    @property
    def clean_ticket_note(self):
        if not self.ticket_note:
            return ""
        import re
        return re.sub(r"<!--TRAVEL_MODE:.*?-->", "", self.ticket_note, flags=re.S).strip()

    @property
    def status_label(self):
        return STATUSES.get(self.status, self.status)

    @property
    def first_arrival(self):
        return min((g.arrival for g in self.guests), default=None)

    @property
    def last_departure(self):
        return max((g.departure for g in self.guests), default=None)

    @property
    def anyone_checked_in(self):
        return any(g.checked_in_at for g in self.guests)

    @property
    def accommodation_summary(self):
        kinds = {STAY_TYPES[g.stay_type] for g in self.guests if g.stay_type in ("guest_house", "hotel")}
        return " / ".join(sorted(kinds)) or "-"


class Guest(db.Model):
    __tablename__ = "gh_guests"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("gh_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    gender = db.Column(db.String(20))
    mobile = db.Column(db.String(30))
    email = db.Column(db.String(150))
    organisation = db.Column(db.String(200))
    designation = db.Column(db.String(150))
    arrival = db.Column(db.DateTime, nullable=False)
    departure = db.Column(db.DateTime, nullable=False)

    # Filled by the desk
    stay_type = db.Column(db.String(20))  # guest_house / hotel / none
    room_id = db.Column(db.Integer, db.ForeignKey("gh_rooms.id"), index=True)
    hotel_id = db.Column(db.Integer, db.ForeignKey("gh_hotels.id"))
    hotel_booking_ref = db.Column(db.String(100))
    hotel_room_no = db.Column(db.String(30))
    hotel_cost = db.Column(db.Float)
    checked_in_at = db.Column(db.DateTime)
    checked_out_at = db.Column(db.DateTime)
    remarks = db.Column(db.String(255))

    request = db.relationship("GuestRequest", back_populates="guests")
    room = db.relationship("Room")
    hotel = db.relationship("Hotel")

    @property
    def nights(self):
        return max(1, (self.departure.date() - self.arrival.date()).days)

    def span(self, now=None):
        """When this guest actually holds the room. Overstay keeps it blocked until check-out."""
        now = now or datetime.now()
        start = self.checked_in_at or self.arrival
        if self.checked_out_at:
            return start, self.checked_out_at
        if self.checked_in_at:
            return start, max(self.departure, now)
        return start, self.departure

    @property
    def stay_label(self):
        if self.stay_type == "guest_house" and self.room:
            return f"{self.room}"
        if self.stay_type == "hotel" and self.hotel:
            return f"{self.hotel.name}" + (f" - room {self.hotel_room_no}" if self.hotel_room_no else "")
        return STAY_TYPES.get(self.stay_type, "Not assigned")


class Trip(db.Model):
    """One vehicle movement. Company vehicle from the master, or a hired one with its details."""
    __tablename__ = "gh_trips"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("gh_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    trip_type = db.Column(db.String(30), nullable=False)
    pickup = db.Column(db.String(200))
    drop = db.Column(db.String(200))
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    source = db.Column(db.String(20), nullable=False)  # company / hired
    vehicle_id = db.Column(db.Integer, db.ForeignKey("gh_vehicles.id"), index=True)
    vendor = db.Column(db.String(150))
    hired_vehicle_no = db.Column(db.String(30))
    hired_vehicle_type = db.Column(db.String(50))
    driver_name = db.Column(db.String(150))
    driver_phone = db.Column(db.String(50))
    cost = db.Column(db.Float)
    remarks = db.Column(db.String(255))

    request = db.relationship("GuestRequest", back_populates="trips")
    vehicle = db.relationship("Vehicle")

    @property
    def vehicle_label(self):
        if self.source == "company" and self.vehicle:
            return str(self.vehicle)
        return f"Hired: {self.hired_vehicle_no or '-'} {self.hired_vehicle_type or ''} ({self.vendor or 'vendor n/a'})".strip()



def _overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def room_conflicts(room_id, start, end, exclude_request_id=None):
    """Guests of *other* live requests holding room_id at any time in [start, end)."""
    q = Guest.query.join(GuestRequest).filter(
        Guest.room_id == room_id, Guest.stay_type == "guest_house", GuestRequest.status.in_(BOOKED))
    if exclude_request_id:
        q = q.filter(Guest.request_id != exclude_request_id)
    now = datetime.now()
    return [g for g in q if _overlaps(g.span(now), (start, end))]


def vehicle_conflicts(vehicle_id, start, end, exclude_request_id=None):
    q = Trip.query.join(GuestRequest).filter(
        Trip.vehicle_id == vehicle_id, Trip.source == "company", GuestRequest.status.in_(BOOKED),
        Trip.start < end, Trip.end > start)
    if exclude_request_id:
        q = q.filter(Trip.request_id != exclude_request_id)
    return q.all()


def room_board(day):
    """{room: [guests holding it on that day]} for every room, incl. inactive ones."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    now = datetime.now()
    busy = {}
    q = Guest.query.join(GuestRequest).filter(Guest.stay_type == "guest_house", Guest.room_id.isnot(None),
                                              GuestRequest.status.in_(BOOKED))
    for g in q:
        if _overlaps(g.span(now), (start, end)):
            busy.setdefault(g.room_id, []).append(g)
    rooms = Room.query.join(GuestHouse).order_by(GuestHouse.name, Room.room_no).all()
    return [(room, busy.get(room.id, [])) for room in rooms]
