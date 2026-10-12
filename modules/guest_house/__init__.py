from core.registry import AppDef

from .views import CODE, approval_record, badge, bp, on_approval, user_requests

APP = AppDef(
    code=CODE,
    name="Guest House",
    icon="guest_house",
    description="Guest requisition: stay, hotel, vehicle, food and tickets for visitors.",
    blueprint=bp,
    home_endpoint="guest_house.index",
    permissions={"desk": "Admin desk - allocate rooms, hotels, vehicles, food & tickets; check guests in/out"},
    settings={
        "request_prefix": {"label": "Request number prefix", "type": "text", "default": "GR"},
        "max_guests": {"label": "Max guests per request", "type": "int", "default": 25},
        "max_stay_days": {"label": "Max stay length (days)", "type": "int", "default": 30},
        "min_notice_hours": {"label": "Minimum notice before arrival (hours)", "type": "int", "default": 0,
                             "help": "0 = same-day requests allowed."},
        "allow_backdated": {"label": "Allow arrival dates in the past", "type": "bool", "default": False,
                            "help": "Useful for regularising unplanned stays."},
        "notify_desk_on_submit": {"label": "Tell the desk about new requests before approval", "type": "bool",
                                  "default": False, "help": "Gives the desk a heads-up to hold rooms or hotels."},
    },
    conditions={
        "needs_guest_house": "Guest house requested",
        "needs_hotel": "Hotel requested",
        "needs_vehicle": "Vehicle requested",
        "needs_ticket": "Travel ticket requested",
        "not_company_paid": "Expenses not borne by Company",
        "large_group": "More than 4 guests",
    },
    approval_record=approval_record,
    on_approval=on_approval,
    badge=badge,
    user_requests=user_requests,
)
