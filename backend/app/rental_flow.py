"""The deterministic 10-step ZoomRideXX WhatsApp booking flow.

Every tap is matched against the step that produced it (state is persisted in
the settings table by app.conversation_state), so the journey works even after
a restart and never depends on the model remembering where the customer is:

    1. language          English / हिंदी
    2. browse cars       Category · Duration · Name · All Cars · Rules · Desk
    3. pick a car        native horizontal carousel (Book Now / View Details)
    4. car card          photo + 6h/12h/24h rates + Previous/Next car
    6. drive mode        Self-Drive / With Chauffeur
    7. schedule          date → time → Hub Self-Pickup / Doorstep Delivery
    8. digital KYC       photos on WhatsApp or show originals at handover
    9. summary           rent + refundable deposit + cleanliness guarantee
   10. confirmation      reference + owner alert to the fleet desk

Money is computed only by app.bookings; this module merely gathers the
customer's choices and renders the messages.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.bookings import confirm_draft, create_draft, draft_for, validate_window
from app.conversation_state import (
    clear_state,
    get_state,
    has_been_welcomed,
    mark_welcomed,
    set_state,
)
from app.database import Booking, Customer, Vehicle
from app.media import public_url, resolve, resolve_vehicle_image
from app.menu import (
    ADDRESS_INVALID,
    ADDRESS_PROMPT,
    BROWSE_ALL_ID,
    BROWSE_CATEGORY_ID,
    BROWSE_DURATION_ID,
    BROWSE_INTRO,
    BROWSE_NAME_ID,
    BROWSE_RETURNING,
    CALL_DESK_TEXT,
    CAR_BOOK_LABEL,
    CAR_BOOK_PREFIX,
    CAR_PREFIX,
    CAR_VIEW_LABEL,
    CAR_VIEW_PREFIX,
    CAT_PREFIX,
    CONFIRM_BOOKING_ID,
    DATE_INVALID,
    DATE_PAST,
    DATE_PROMPT,
    DATE_TODAY,
    DATE_TODAY_ID,
    DATE_TOMORROW,
    DATE_TOMORROW_ID,
    DESK_NUMBERS,
    DRIVE_CHAUFFEUR_ID,
    DRIVE_CHAUFFEUR_LABEL,
    DRIVE_MODE_INTRO,
    DRIVE_SELF_ID,
    DRIVE_SELF_LABEL,
    DUR_PREFIX,
    FLEET_CAROUSEL_INTRO,
    HANDOVER_DOOR_ID,
    HANDOVER_HUB_ID,
    HANDOVER_PROMPT,
    HUB_ADDRESS,
    HUB_LABEL,
    DOOR_LABEL,
    INTRO,
    IST,
    KYC_DONE,
    KYC_DONE_LABEL,
    KYC_HANDOVER_ID,
    KYC_HANDOVER_LABEL,
    KYC_ONE_RECEIVED,
    KYC_PROMPT,
    KYC_SEND_LABEL,
    KYC_WAITING,
    KYC_WHATSAPP_ID,
    LANG_CONFIRM,
    MAX_ROWS,
    MENU_BOOK_CAR_ID,
    MENU_CALL_DESK_ID,
    MENU_DEPOSIT_KYC_ID,
    MENU_HOME_ID,
    MENU_LANG_ID,
    MENU_MY_BOOKINGS_ID,
    MENU_QUERY_ID,
    NAME_NOT_FOUND,
    NAME_PROMPT,
    NEXT_CAR_ID,
    NO_CARS,
    PREV_CAR_ID,
    RULES_TEXT,
    START_OVER_ID,
    TIME_INVALID,
    TIME_PREFIX,
    TIME_PROMPT,
    budget_note,
    car_card_text,
    car_carousel_body,
    car_row,
    confirmed_text,
    date_prompt,
    drive_mode_intro,
    failure_text,
    list_payload,
    list_row,
    matching_vehicle,
    money,
    owner_alert_text,
    summary_text,
    time_rows,
)
from app.outgoing import CarouselCard, Outgoing
from app.vehicles import (
    categories as fleet_categories,
    find_vehicle,
    offers_packages,
    package_price,
)

log = logging.getLogger("zoomride.flow")

Sink = Callable[[Outgoing], Awaitable[None]]

# --------------------------------------------------------------------------- #
# states
# --------------------------------------------------------------------------- #
WELCOME = "welcome"
MENU = "menu"
BROWSE = "browse"
NAME = "name"
DURATION = "duration"   # package for a chosen car
DRIVE = "drive"
PICK_DATE = "date"
PICK_TIME = "time"
HANDOVER = "handover"
ADDRESS = "address"
KYC = "kyc"
KYC_WAIT = "kyc_wait"
SUMMARY = "summary"

CATEGORY_ORDER = ["SUV & 4x4", "Compact SUV", "Sedan", "Hatchback & MUV"]

# Website "Book on WhatsApp" deep links arrive as structured text, e.g.
#   Hi ZoomRideXX! 🚗
#   I'd like to book the *Mahindra Thar Roxx* (ZR-THAR-ROXX).
#   • Package: 24 hours
#   • Mode: Self-drive
#   • Handover: Hub self-pickup
# These messages carry a REAL booking intent — route them into the
# deterministic flow (car photo + rate card + tappable next steps) instead of
# leaving them to a plain-text LLM reply.
WEBSITE_BOOK_RE = re.compile(
    r"book the \*?(?P<vehicle>[^*()\n]+?)\*?\s*\(\s*(?P<code>[A-Za-z]{2,6}-[A-Za-z0-9-]{2,24})\s*\)",
)
WEBSITE_PACKAGE_RE = re.compile(r"Package:\s*(\d+)\s*hours?", re.IGNORECASE)
WEBSITE_MODE_RE = re.compile(r"Mode:\s*([^\n•]+)", re.IGNORECASE)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _lang(table: dict[str, str], lang: str) -> str:
    return table.get(lang) or table["en"]


def _label(table: dict[str, str], lang: str) -> str:
    return _lang(table, lang)


def _main_menu(lang: str, returning: bool = False) -> Outgoing:
    """The home screen is the browse-cars screen — no separate main menu."""
    return _browse_outgoing(lang, returning=returning)


def _vehicle_media(v: Vehicle) -> tuple[str, str]:
    """(servable URL, registry id) for one fleet row — ('','') when none."""
    try:
        url, image_id = resolve_vehicle_image(
            v.image_url or "",
            code=v.code or "",
            name=v.name or "",
            category=v.category or "",
            description=v.description or "",
        )
        if image_id:
            entry = resolve(image_id)
            if entry is not None:
                url = public_url(entry)
        return url, image_id
    except Exception as exc:  # noqa: BLE001
        log.info("vehicle image lookup failed for %s: %s", v.code, exc)
        return "", ""


def _listed(db: DBSession) -> list[Vehicle]:
    rows = db.execute(select(Vehicle).where(Vehicle.available == 1)).scalars().all()

    def order(v: Vehicle) -> tuple[int, str]:
        try:
            idx = CATEGORY_ORDER.index(v.category or "")
        except ValueError:
            idx = len(CATEGORY_ORDER)
        return idx, (v.name or "")

    return sorted(rows, key=order)


def _browse_outgoing(
    lang: str, *, returning: bool = False, greeting: str = "",
) -> Outgoing:
    rows = [
        list_row(BROWSE_CATEGORY_ID, "📂 By Category", "SUV, compact SUV, sedan or hatchback"),
        list_row(BROWSE_DURATION_ID, "⏱ By Duration", "6-hour, 12-hour or 24-hour package"),
        list_row(BROWSE_NAME_ID, "⌨️ Type Car Name", "Tell me the model you have in mind"),
        list_row(BROWSE_ALL_ID, "🚗 See All Cars", "Browse the fleet one car at a time"),
        list_row(MENU_DEPOSIT_KYC_ID, "📄 Deposit & KYC", "Security deposit and documents"),
        list_row(MENU_CALL_DESK_ID, "📞 Fleet Desk", "Talk to our team"),
    ]
    text = _lang(BROWSE_RETURNING if returning else BROWSE_INTRO, lang)
    if greeting:
        text = f"{greeting}\n\n{text}"
    return Outgoing(
        text=text,
        intent="VEHICLE_SEARCH",
        interactive_list=list_payload(rows, "Browse cars"),
    )


def _category_outgoing(db: DBSession, lang: str) -> Outgoing:
    counts: dict[str, int] = {}
    for v in _listed(db):
        key = (v.category or "Other").strip()
        counts[key] = counts.get(key, 0) + 1
    names = [c for c in CATEGORY_ORDER if c in counts] + [
        c for c in counts if c not in CATEGORY_ORDER
    ]
    rows = [
        list_row(CAT_PREFIX + _slug(name), name,
                 f"{counts[name]} car{'s' if counts[name] != 1 else ''}")
        for name in names[:MAX_ROWS]
    ]
    if not rows:
        return Outgoing(text=_lang(NO_CARS, lang), intent="VEHICLE_SEARCH",
                        buttons=[(MENU_HOME_ID, "🚗 Browse Cars")])
    return Outgoing(
        text="Pick a category and I'll show you the cars available in it.",
        intent="VEHICLE_SEARCH",
        interactive_list=list_payload(rows, "Pick a category"),
    )


def _duration_minimum(db: DBSession, hours: int) -> float | None:
    prices = [
        package_price(v, hours) for v in _listed(db) if package_price(v, hours)
    ]
    return min(prices) if prices else None


def _duration_outgoing(db: DBSession, lang: str) -> Outgoing:
    rows = []
    for hours in (6, 12, 24):
        minimum = _duration_minimum(db, hours)
        if minimum is None:
            continue
        note = "City errands and short trips" if hours == 6 else (
            "Half-day and airport runs" if hours == 12 else "Full-day and outstation")
        rows.append(list_row(
            f"{DUR_PREFIX}{hours}", f"{hours} hours",
            f"{note} · from {money(minimum)}",
        ))
    if not rows:
        return Outgoing(text=_lang(NO_CARS, lang), intent="VEHICLE_SEARCH",
                        buttons=[(MENU_HOME_ID, "🚗 Browse Cars")])
    return Outgoing(
        text="Which package works for you? I'll show the cars and their exact price for that duration.",
        intent="PRICE_QUERY",
        interactive_list=list_payload(rows, "Pick a package"),
    )


def _fleet_carousel_outgoing(
    vehicles: list[Vehicle], lang: str, *, heading: str = "",
    hours: int | None = None, part: int = 1, parts: int = 1,
) -> Outgoing | None:
    """One swipeable carousel (max 10 cards) for any fleet view."""
    cards: list[CarouselCard] = []
    for v in vehicles[:MAX_ROWS]:
        url, image_id = _vehicle_media(v)
        if not (url or image_id):
            continue
        cards.append(CarouselCard(
            image_id=image_id,
            image_url=url,
            body_text=car_carousel_body(v, lang, hours),
            buttons=[
                (CAR_BOOK_PREFIX + (v.code or ""), _label(CAR_BOOK_LABEL, lang)),
                (CAR_VIEW_PREFIX + (v.code or ""), _label(CAR_VIEW_LABEL, lang)),
            ],
        ))
    if len(cards) < 2:
        return None
    text = _lang(FLEET_CAROUSEL_INTRO, lang)
    if heading:
        text = f"*{heading}*\n\n{text}"
    if parts > 1:
        text += ("\n\n_भाग {part}/{parts}_" if lang == "hi" else "\n\n_Part {part} of {parts}_").format(
            part=part, parts=parts,
        )
    return Outgoing(text=text, intent="VEHICLE_SEARCH", carousel=cards)


async def _send_car_list(
    db: DBSession, sink: Sink, lang: str, vehicles: list[Vehicle], *,
    heading: str = "", hours: int | None = None,
) -> None:
    """Show every matching car as a horizontal carousel.

    WhatsApp caps a carousel at 10 cards, so a larger fleet is split into
    consecutive carousels with identical cards and actions.
    """
    if not vehicles:
        await sink(Outgoing(text=_lang(NO_CARS, lang), intent="VEHICLE_SEARCH",
                            buttons=[(MENU_HOME_ID, "🚗 Browse Cars")]))
        return
    chunks = [vehicles[i:i + MAX_ROWS] for i in range(0, len(vehicles), MAX_ROWS)]
    sent = 0
    for index, chunk in enumerate(chunks):
        outgoing = _fleet_carousel_outgoing(
            chunk, lang, heading=heading, hours=hours,
            part=index + 1, parts=len(chunks))
        if outgoing is None:
            continue
        await sink(outgoing)
        sent += 1
    if sent:
        return
    # No sendable photos at all: keep the fleet reachable with the old list.
    rows = [car_row(v, hours) for v in vehicles[:MAX_ROWS]]
    title = heading or (f"{hours}-hour packages" if hours else "Our fleet")
    await sink(Outgoing(
        text=f"*{title}*\n\nTap the car you'd like to see.",
        intent="VEHICLE_SEARCH",
        interactive_list=list_payload(rows, "View cars"),
    ))


def _scope_vehicles(db: DBSession, scope: str) -> list[Vehicle]:
    """The cars a carousel is swiping through: all, one category or one package."""
    scope = (scope or "").strip()
    rows = _listed(db)
    if scope.startswith("cat:"):
        category = scope[len("cat:"):]
        rows = [v for v in rows if (v.category or "").lower() == category.lower()]
    elif scope.startswith("dur:"):
        try:
            hours = int(scope[len("dur:"):])
        except ValueError:
            hours = 0
        rows = [v for v in rows if package_price(v, hours)] if hours in (6, 12, 24) else []
    return rows


async def _send_car_card(
    db: DBSession, sink: Sink, v: Vehicle, lang: str, scope: str = "all",
) -> None:
    """Detail view for one car: photo bubble first, then rates + navigation.

    The fleet itself is browsed in the native hotel-style carousel; this screen
    is what a carousel card opens, with the package rows and Previous/Next.
    """
    vehicles = _scope_vehicles(db, scope) or _listed(db)
    index = next((i for i, row in enumerate(vehicles) if row.id == v.id), 0)
    total = len(vehicles)
    position = f"Car {index + 1} of {total}"
    url, image_id = _vehicle_media(v)
    if url or image_id:
        await sink(Outgoing(
            text="",
            intent="VEHICLE_SEARCH",
            image_url=url,
            image_id=image_id,
            image_caption=f"{v.name} · {position}",
        ))
    rows: list[dict[str, str]] = []
    for hours in offers_packages(v):
        price = package_price(v, hours)
        if price:
            rows.append(list_row(
                f"{DUR_PREFIX}{hours}", f"{hours} hours", f"{money(price)} · tap to book",
            ))
    rows.append(list_row(PREV_CAR_ID, "◀ Previous car", "See the previous car"))
    rows.append(list_row(NEXT_CAR_ID, "Next car ▶", "See the next car"))
    rows.append(list_row(
        MENU_BOOK_CAR_ID, "🔎 Browse other cars", "By category, duration or name",
    ))
    await sink(Outgoing(
        text=car_card_text(v, lang, position=position),
        intent="VEHICLE_SEARCH",
        interactive_list=list_payload(rows, "Choose an option"),
    ))


def _drive_outgoing(v: Vehicle, hours: int, lang: str) -> Outgoing:
    return Outgoing(
        text=drive_mode_intro(lang, v, hours, package_price(v, hours) or 0),
        intent="BOOKING",
        buttons=[
            (DRIVE_SELF_ID, _label(DRIVE_SELF_LABEL, lang)),
            (DRIVE_CHAUFFEUR_ID, _label(DRIVE_CHAUFFEUR_LABEL, lang)),
        ],
    )


def _date_outgoing(lang: str) -> Outgoing:
    return Outgoing(
        text=date_prompt(lang),
        intent="BOOKING",
        buttons=[
            (DATE_TODAY_ID, _label(DATE_TODAY, lang)),
            (DATE_TOMORROW_ID, _label(DATE_TOMORROW, lang)),
        ],
    )


def _time_outgoing(lang: str) -> Outgoing:
    return Outgoing(
        text=_lang(TIME_PROMPT, lang),
        intent="BOOKING",
        interactive_list=list_payload(time_rows(lang), "Pick a time"),
    )


def _handover_outgoing(lang: str) -> Outgoing:
    return Outgoing(
        text=_lang(HANDOVER_PROMPT, lang),
        intent="BOOKING",
        buttons=[
            (HANDOVER_HUB_ID, _label(HUB_LABEL, lang)),
            (HANDOVER_DOOR_ID, _label(DOOR_LABEL, lang)),
        ],
    )


# --------------------------------------------------------------------------- #
# date/time parsing (deterministic — never guess a slot from the model)
# --------------------------------------------------------------------------- #
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_TODAY_WORDS = {"today", "aaj", "आज", "aj"}
_TOMORROW_WORDS = {"tomorrow", "kal", "कल", "tmrw", "tom"}


def _today_ist() -> date:
    return datetime.now(IST).date()


def parse_date_text(text: str) -> date | None:
    raw = (text or "").strip().lower()
    if not raw:
        return None
    words = set(re.findall(r"[a-z\u0900-\u097F]+", raw))
    if words & _TODAY_WORDS:
        return _today_ist()
    if words & _TOMORROW_WORDS:
        return _today_ist() + timedelta(days=1)

    match = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", raw)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.search(r"\b(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?\b", raw)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else _today_ist().year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})(?:\s*,?\s*(20\d{2}))?\b", raw)
    if match:
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2))
        year = int(match.group(3)) if match.group(3) else _today_ist().year
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None
    match = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(20\d{2}))?\b", raw)
    if match:
        month = _MONTHS.get(match.group(1))
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else _today_ist().year
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def parse_time_text(text: str) -> time | None:
    raw = (text or "").strip().lower()
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b", raw)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = (match.group(3) or "").replace(".", "")
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _slot(data: dict[str, Any], hours: int) -> tuple[datetime, datetime] | None:
    try:
        day = date.fromisoformat(str(data.get("date") or ""))
        clock = time.fromisoformat(str(data.get("time") or ""))
    except (TypeError, ValueError):
        return None
    start = datetime.combine(day, clock).replace(tzinfo=IST)
    return start, start + timedelta(hours=hours)


def _slot_problem(start: datetime, end: datetime) -> str:
    return validate_window(start, end)


# --------------------------------------------------------------------------- #
# owner alert
# --------------------------------------------------------------------------- #
async def _notify_owners(booking, vehicle: Vehicle, customer: Customer, address: str) -> None:
    from app.config import OWNER_WHATSAPP_NUMBERS
    from app.kapso import kapso, normalize_phone

    text = owner_alert_text(booking, vehicle, customer, address)
    for raw in OWNER_WHATSAPP_NUMBERS:
        number = normalize_phone(raw)
        if not number:
            continue
        try:
            await kapso.send_text(number, text)
            log.info("booking %s alert sent to …%s", booking.reference, number[-4:])
        except Exception as exc:  # noqa: BLE001
            # The booking stands even when the alert cannot be delivered; the
            # console conversation still shows it for the team.
            log.warning("owner alert to …%s failed: %s", number[-4:], exc)


# --------------------------------------------------------------------------- #
# summary + confirmation
# --------------------------------------------------------------------------- #
async def _finalize_summary(
    db: DBSession, ctx, inbound, lang: str, sink: Sink,
    data: dict[str, Any], kyc_mode: str,
) -> bool:
    car_code = str(data.get("car_code") or "")
    hours = int(data.get("hours") or 0)
    vehicle = find_vehicle(db, car_code)
    slot = _slot(data, hours)
    if vehicle is None or slot is None:
        set_state(db, ctx.conversation.id, PICK_DATE)
        await sink(Outgoing(
            text="That booking window expired 🙏 Let's set it again — when should we hand over the car?",
            intent="BOOKING",
            buttons=[
                (DATE_TODAY_ID, _label(DATE_TODAY, lang)),
                (DATE_TOMORROW_ID, _label(DATE_TOMORROW, lang)),
            ],
        ))
        return True
    start, end = slot
    problem = _slot_problem(start, end)
    if problem:
        set_state(db, ctx.conversation.id, PICK_TIME, **{
            k: v for k, v in data.items() if k != "time"
        })
        await sink(Outgoing(
            text=f"That slot doesn't work any more 🙏 ({problem}). Please pick another time.",
            intent="BOOKING",
            interactive_list=list_payload(time_rows(lang), "Pick a time"),
        ))
        return True

    address = str(data.get("address") or "")
    handover = str(data.get("handover") or "hub")
    drive = str(data.get("drive") or "self")
    draft = create_draft(
        db,
        customer=ctx.customer,
        vehicle=vehicle,
        start=start,
        end=end,
        pickup_location=HUB_ADDRESS if handover == "hub" else address,
        dropoff_location=HUB_ADDRESS if handover == "hub" else address,
        with_driver=(drive == "chauffeur"),
        delivery=(handover == "doorstep"),
        conversation_id=ctx.conversation.id,
        hours=hours,
        drive_mode=drive,
        handover=handover,
        kyc_mode=kyc_mode,
    )
    db.flush()
    set_state(db, ctx.conversation.id, SUMMARY)
    url, image_id = _vehicle_media(vehicle)
    await sink(Outgoing(
        text=summary_text(lang, draft, vehicle, address),
        intent="BOOKING",
        buttons=[(CONFIRM_BOOKING_ID, "✅ Confirm Booking")],
        image_url=url,
        image_id=image_id,
        image_caption=f"{vehicle.name} · {budget_note(vehicle)}",
    ))
    return True


async def confirm_booking(
    db: DBSession, ctx, inbound, lang: str, sink: Sink, deliver: bool,
) -> bool:
    """Confirm the open draft (idempotent) and alert the fleet desk."""
    draft = draft_for(db, ctx.conversation.id)
    if draft is None:
        recent = db.execute(
            select(Booking)
            .where(
                Booking.customer_id == ctx.customer.id,
                Booking.status == "confirmed",
                Booking.notes.like(f"%conv={ctx.conversation.id}%"),
            )
            .order_by(Booking.id.desc())
        ).scalars().first()
        text = (
            f"This booking is already confirmed ✅ If you'd like to change anything, "
            f"call our fleet desk on {DESK_NUMBERS[0]}."
            if recent is not None else
            "I don't have an open booking to confirm 🙏 Let's pick a car first."
        )
        await sink(Outgoing(
            text=text,
            intent="BOOKING_QUERY",
            buttons=[(MENU_HOME_ID, "🚗 Browse Cars")],
        ))
        return True

    booking, reason = confirm_draft(
        db, draft=draft, confirming_message_id=inbound.message_id)
    if booking is None:
        set_state(db, ctx.conversation.id, SUMMARY)
        await sink(Outgoing(
            text=failure_text(lang, reason),
            intent="BOOKING",
            buttons=[
                (MENU_BOOK_CAR_ID, "🚗 Book another car"),
                (MENU_CALL_DESK_ID, "📞 Fleet Desk"),
            ],
        ))
        return True

    vehicle = db.get(Vehicle, booking.vehicle_id)
    address = ""
    if booking.handover == "doorstep":
        address = booking.pickup_location or ""
    url, image_id = _vehicle_media(vehicle) if vehicle else ("", "")
    await sink(Outgoing(
        text=confirmed_text(lang, booking, vehicle) if vehicle else
        f"✅ Booking confirmed — {booking.reference}",
        intent="BOOKING",
        buttons=[
            (MENU_HOME_ID, "🚗 Browse Cars"),
            (MENU_CALL_DESK_ID, "📞 Fleet Desk"),
        ],
        image_url=url,
        image_id=image_id,
        image_caption=(vehicle.name if vehicle else "Your car"),
    ))
    clear_state(db, ctx.conversation.id)
    set_state(db, ctx.conversation.id, MENU)
    if deliver and vehicle is not None:
        await _notify_owners(booking, vehicle, ctx.customer, address)
    log.info("booking %s confirmed for %s", booking.reference, inbound.wa_id)
    return True


# --------------------------------------------------------------------------- #
# main dispatcher
# --------------------------------------------------------------------------- #
async def handle(
    db: DBSession, ctx, inbound, lang: str, sink: Sink, *, deliver: bool,
) -> bool:
    """Handle one turn deterministically. False → let the LLM answer."""
    conversation_id = ctx.conversation.id
    bid = (inbound.button_id or "").strip()
    text = (inbound.text or "").strip()
    lowered = text.lower()
    state = get_state(db, conversation_id)
    step = str(state.get("state") or "")
    data: dict[str, Any] = dict(state.get("data") or {})
    has_media = bool(inbound.media) or (inbound.msg_type or "") in {
        "image", "document", "video",
    }

    # ---------------- website deep-link booking ---------------- #
    # A "Book on WhatsApp" tap on the website carries the car code, package
    # and drive mode. Seed the flow with those choices and show the SAME rich
    # experience as browsing: car photo, rate card, tappable next steps.
    # Runs BEFORE the first-contact intro: the structured message already
    # proves intent and language, so a brand-new customer goes straight into
    # the interactive booking flow.
    wa_booking = WEBSITE_BOOK_RE.search(text)
    if wa_booking:
        vehicle = find_vehicle(db, wa_booking.group("code"))
        if vehicle is not None:
            if not has_been_welcomed(db, conversation_id):
                mark_welcomed(db, conversation_id)
            package = WEBSITE_PACKAGE_RE.search(text)
            hours = int(package.group(1)) if package else 0
            mode_match = WEBSITE_MODE_RE.search(text)
            mode_text = (mode_match.group(1) if mode_match else "").lower()
            drive = "chauffeur" if "chauffeur" in mode_text else "self"
            if hours in (6, 12, 24) and package_price(vehicle, hours):
                set_state(
                    db, conversation_id, PICK_DATE,
                    car_code=vehicle.code, hours=hours, drive=drive,
                )
                await _send_car_card(db, sink, vehicle, lang, "all")
                intro = ""
                if drive == "chauffeur":
                    from app.menu import CHAUFFEUR_NOTE

                    intro = _lang(CHAUFFEUR_NOTE, lang) + "\n\n"
                await sink(Outgoing(
                    text=intro + _lang(DATE_PROMPT, lang),
                    intent="BOOKING",
                    buttons=[
                        (DATE_TODAY_ID, _label(DATE_TODAY, lang)),
                        (DATE_TOMORROW_ID, _label(DATE_TOMORROW, lang)),
                    ],
                ))
            else:
                # package missing or not offered for this car — let the
                # customer pick one from the rate card
                set_state(
                    db, conversation_id, DURATION,
                    car_code=vehicle.code, scope="all",
                )
                await _send_car_card(db, sink, vehicle, lang, "all")
            return True
        # unknown code → fall through to the normal flow below

    # ---------------- first contact ---------------- #
    if not has_been_welcomed(db, conversation_id):
        mark_welcomed(db, conversation_id)
        set_state(db, conversation_id, WELCOME)
        await sink(Outgoing(
            text=_lang(INTRO, "en"),
            intent="GENERAL_ENQUIRY",
            buttons=[("lang_en", "English"), ("lang_hi", "हिंदी")],
        ))
        return True

    # ---------------- language buttons ---------------- #
    if bid.startswith("lang_"):
        chosen = bid[len("lang_"):]
        if chosen in {"en", "hi"}:
            set_state(db, conversation_id, MENU)
            await sink(_browse_outgoing(
                chosen, greeting=_lang(LANG_CONFIRM, chosen)))
        else:
            await sink(Outgoing(
                text="Please choose English or हिंदी.",
                buttons=[("lang_en", "English"), ("lang_hi", "हिंदी")],
            ))
            set_state(db, conversation_id, WELCOME)
        return True

    # ---------------- main menu ---------------- #
    if bid == MENU_HOME_ID or bid == START_OVER_ID:
        set_state(db, conversation_id, MENU)
        await sink(_main_menu(lang, returning=True))
        return True

    if bid == MENU_LANG_ID:
        await sink(Outgoing(
            text="Choose your language / अपनी भाषा चुनिए",
            buttons=[("lang_en", "English"), ("lang_hi", "हिंदी")],
        ))
        return True

    if bid == MENU_QUERY_ID:
        await sink(Outgoing(
            text=(
                "Sure — type your question and I'll help. You can ask about a car, "
                "rates, documents, delivery or your booking."
            ),
            intent="GENERAL_ENQUIRY",
            buttons=[(MENU_HOME_ID, "🚗 Browse Cars")],
        ))
        set_state(db, conversation_id, MENU)
        return True

    if bid == MENU_BOOK_CAR_ID:
        set_state(db, conversation_id, MENU)
        await sink(_browse_outgoing(lang))
        return True

    if bid == MENU_DEPOSIT_KYC_ID:
        set_state(db, conversation_id, MENU)
        await sink(Outgoing(
            text=_lang(RULES_TEXT, lang),
            intent="POLICY_QUERY",
            buttons=[
                (MENU_HOME_ID, "🚗 Browse Cars"),
                (MENU_CALL_DESK_ID, "📞 Fleet Desk"),
            ],
        ))
        return True

    if bid == MENU_CALL_DESK_ID:
        set_state(db, conversation_id, MENU)
        await sink(Outgoing(
            text=_lang(CALL_DESK_TEXT, lang),
            intent="HUMAN_HANDOFF",
            buttons=[(MENU_HOME_ID, "🚗 Browse Cars")],
        ))
        return True

    if bid == MENU_MY_BOOKINGS_ID:
        from app.bookings import booking_summary, customer_bookings

        rows = customer_bookings(db, ctx.customer.id, limit=5)
        if not rows:
            await sink(Outgoing(
                text="You have no active bookings right now 🙏 Want me to show the fleet?",
                intent="BOOKING_QUERY",
                buttons=[(MENU_HOME_ID, "🚗 Browse Cars")],
            ))
        else:
            lines = ["Here are your bookings 📅"]
            for b in rows:
                lines.append("• " + booking_summary(b, db.get(Vehicle, b.vehicle_id)))
            await sink(Outgoing(
                text="\n".join(lines),
                intent="BOOKING_QUERY",
                buttons=[(MENU_HOME_ID, "🚗 Browse Cars")],
            ))
        return True

    # ---------------- browse ---------------- #
    if bid == BROWSE_CATEGORY_ID:
        set_state(db, conversation_id, BROWSE, mode="category")
        await sink(_category_outgoing(db, lang))
        return True

    if bid == BROWSE_DURATION_ID:
        set_state(db, conversation_id, BROWSE, mode="duration")
        await sink(_duration_outgoing(db, lang))
        return True

    if bid == BROWSE_NAME_ID:
        set_state(db, conversation_id, NAME)
        await sink(Outgoing(
            text=_lang(NAME_PROMPT, lang),
            intent="VEHICLE_SEARCH",
            buttons=[(BROWSE_CATEGORY_ID, "📂 Browse by category")],
        ))
        return True

    if bid == BROWSE_ALL_ID:
        vehicles = _listed(db)
        if not vehicles:
            await sink(Outgoing(
                text=_lang(NO_CARS, lang),
                intent="VEHICLE_SEARCH",
                buttons=[(MENU_HOME_ID, "🚗 Browse Cars")],
            ))
            return True
        set_state(db, conversation_id, BROWSE, mode="all")
        await _send_car_list(
            db, sink, lang, vehicles, heading="Our complete fleet")
        return True

    # ---------------- category tap ---------------- #
    if bid.startswith(CAT_PREFIX):
        slug = bid[len(CAT_PREFIX):]
        names = fleet_categories(db)
        category = next((n for n in names if _slug(n) == slug), "")
        if not category:
            await sink(_category_outgoing(db, lang))
            return True
        set_state(db, conversation_id, BROWSE, mode="category", category=category)
        vehicles = [
            v for v in _listed(db)
            if (v.category or "").lower() == category.lower()
        ]
        await _send_car_list(db, sink, lang, vehicles, heading=category)
        return True

    # ---------------- duration tap ---------------- #
    if bid.startswith(DUR_PREFIX):
        try:
            hours = int(bid[len(DUR_PREFIX):])
        except ValueError:
            hours = 0
        selected_car = str(data.get("car_code") or "")
        if step == DURATION and selected_car and hours in (6, 12, 24):
            vehicle = find_vehicle(db, selected_car)
            price = package_price(vehicle, hours) if vehicle else None
            if vehicle is None or price is None:
                set_state(
                    db, conversation_id, BROWSE, mode="duration", hours=hours)
                vehicles = [
                    v for v in _listed(db) if package_price(v, hours)
                ]
                await _send_car_list(
                    db, sink, lang, vehicles, heading=f"{hours}-hour packages",
                    hours=hours)
                return True
            set_state(
                db, conversation_id, DRIVE,
                car_code=vehicle.code, hours=hours,
            )
            await sink(_drive_outgoing(vehicle, hours, lang))
            return True
        if hours in (6, 12, 24):
            set_state(db, conversation_id, BROWSE, mode="duration", hours=hours)
            vehicles = [v for v in _listed(db) if package_price(v, hours)]
            await _send_car_list(
                db, sink, lang, vehicles, heading=f"{hours}-hour packages",
                hours=hours)
            return True

    # ---------------- carousel card actions ---------------- #
    if bid.startswith(CAR_BOOK_PREFIX) or bid.startswith(CAR_VIEW_PREFIX):
        is_booking = bid.startswith(CAR_BOOK_PREFIX)
        code = bid[len(CAR_BOOK_PREFIX if is_booking else CAR_VIEW_PREFIX):]
        vehicle = find_vehicle(db, code)
        if vehicle is None:
            await sink(_browse_outgoing(lang))
            return True
        set_state(
            db, conversation_id, DURATION,
            car_code=vehicle.code, scope="all",
        )
        await _send_car_card(db, sink, vehicle, lang, "all")
        return True

    # ---------------- car tap ---------------- #
    if bid.startswith(CAR_PREFIX):
        code = bid[len(CAR_PREFIX):]
        vehicle = find_vehicle(db, code)
        if vehicle is None:
            await sink(_browse_outgoing(lang))
            return True
        scope = "all"
        category = str(data.get("category") or "")
        hours = int(data.get("hours") or 0)
        if category:
            scope = f"cat:{category}"
        elif hours in (6, 12, 24):
            scope = f"dur:{hours}"
        set_state(
            db, conversation_id, DURATION,
            car_code=vehicle.code, scope=scope,
        )
        await _send_car_card(db, sink, vehicle, lang, scope)
        return True

    # ---------------- previous / next car ---------------- #
    if bid in (PREV_CAR_ID, NEXT_CAR_ID):
        scope = str(data.get("scope") or "all")
        vehicles = _scope_vehicles(db, scope) or _listed(db)
        if not vehicles:
            await sink(_browse_outgoing(lang))
            return True
        current = find_vehicle(db, str(data.get("car_code") or ""))
        index = next(
            (i for i, row in enumerate(vehicles) if current and row.id == current.id), 0)
        delta = -1 if bid == PREV_CAR_ID else 1
        target = vehicles[(index + delta) % len(vehicles)]
        set_state(
            db, conversation_id, DURATION,
            car_code=target.code, scope=scope,
        )
        await _send_car_card(db, sink, target, lang, scope)
        return True

    # ---------------- drive mode ---------------- #
    if bid in (DRIVE_SELF_ID, DRIVE_CHAUFFEUR_ID):
        vehicle = find_vehicle(db, str(data.get("car_code") or ""))
        hours = int(data.get("hours") or 0)
        if vehicle is None or not hours:
            set_state(db, conversation_id, BROWSE)
            await sink(_browse_outgoing(lang))
            return True
        drive = "chauffeur" if bid == DRIVE_CHAUFFEUR_ID else "self"
        set_state(
            db, conversation_id, PICK_DATE,
            car_code=vehicle.code, hours=hours, drive=drive,
        )
        intro = ""
        if drive == "chauffeur":
            from app.menu import CHAUFFEUR_NOTE

            intro = _lang(CHAUFFEUR_NOTE, lang) + "\n\n"
        await sink(Outgoing(
            text=intro + _lang(DATE_PROMPT, lang),
            intent="BOOKING",
            buttons=[
                (DATE_TODAY_ID, _label(DATE_TODAY, lang)),
                (DATE_TOMORROW_ID, _label(DATE_TOMORROW, lang)),
            ],
        ))
        return True

    # ---------------- date ---------------- #
    if bid in (DATE_TODAY_ID, DATE_TOMORROW_ID):
        day = _today_ist() if bid == DATE_TODAY_ID else _today_ist() + timedelta(days=1)
        set_state(
            db, conversation_id, PICK_TIME,
            car_code=data.get("car_code"), hours=data.get("hours"),
            drive=data.get("drive"), date=day.isoformat(),
        )
        await sink(_time_outgoing(lang))
        return True

    if step == PICK_DATE and text:
        day = parse_date_text(text)
        if day is None:
            await sink(Outgoing(
                text=_lang(DATE_INVALID, lang),
                intent="BOOKING",
                buttons=[
                    (DATE_TODAY_ID, _label(DATE_TODAY, lang)),
                    (DATE_TOMORROW_ID, _label(DATE_TOMORROW, lang)),
                ],
            ))
            return True
        if day < _today_ist():
            await sink(Outgoing(
                text=_lang(DATE_PAST, lang),
                intent="BOOKING",
                buttons=[
                    (DATE_TODAY_ID, _label(DATE_TODAY, lang)),
                    (DATE_TOMORROW_ID, _label(DATE_TOMORROW, lang)),
                ],
            ))
            return True
        set_state(
            db, conversation_id, PICK_TIME,
            car_code=data.get("car_code"), hours=data.get("hours"),
            drive=data.get("drive"), date=day.isoformat(),
        )
        await sink(_time_outgoing(lang))
        return True

    # ---------------- time ---------------- #
    if bid.startswith(TIME_PREFIX):
        raw = bid[len(TIME_PREFIX):]
        clock = parse_time_text(f"{raw[:2]}:{raw[2:]}" if len(raw) == 4 else raw)
        if clock is not None:
            return await _accept_time(db, ctx, inbound, lang, sink, data, clock)
        await sink(Outgoing(
            text=_lang(TIME_INVALID, lang),
            intent="BOOKING",
            interactive_list=list_payload(time_rows(lang), "Pick a time"),
        ))
        return True

    if step == PICK_TIME and text:
        clock = parse_time_text(text)
        if clock is None:
            await sink(Outgoing(
                text=_lang(TIME_INVALID, lang),
                intent="BOOKING",
                interactive_list=list_payload(time_rows(lang), "Pick a time"),
            ))
            return True
        return await _accept_time(db, ctx, inbound, lang, sink, data, clock)

    # ---------------- handover ---------------- #
    if bid == HANDOVER_HUB_ID:
        set_state(
            db, conversation_id, KYC,
            car_code=data.get("car_code"), hours=data.get("hours"),
            drive=data.get("drive"), date=data.get("date"), time=data.get("time"),
            handover="hub",
        )
        await sink(Outgoing(
            text=f"🏢 *Hub Self-Pickup*\n\nYou can collect the car from {HUB_ADDRESS}.\n\n"
                 + _lang(KYC_PROMPT, lang),
            intent="BOOKING",
            buttons=[
                (KYC_WHATSAPP_ID, _label(KYC_SEND_LABEL, lang)),
                (KYC_HANDOVER_ID, _label(KYC_HANDOVER_LABEL, lang)),
            ],
        ))
        return True

    if bid == HANDOVER_DOOR_ID:
        set_state(
            db, conversation_id, ADDRESS,
            car_code=data.get("car_code"), hours=data.get("hours"),
            drive=data.get("drive"), date=data.get("date"), time=data.get("time"),
            handover="doorstep",
        )
        await sink(Outgoing(
            text=_lang(ADDRESS_PROMPT, lang),
            intent="BOOKING",
            buttons=[(HANDOVER_HUB_ID, "🏢 Pick up at hub instead")],
        ))
        return True

    if step == ADDRESS and text:
        if len(re.sub(r"[^\w]", "", text)) < 6:
            await sink(Outgoing(text=_lang(ADDRESS_INVALID, lang), intent="BOOKING"))
            return True
        set_state(
            db, conversation_id, KYC,
            car_code=data.get("car_code"), hours=data.get("hours"),
            drive=data.get("drive"), date=data.get("date"), time=data.get("time"),
            handover="doorstep", address=text[:300],
        )
        await sink(Outgoing(
            text="Got it — we'll bring the car to that address 🏠\n\n" + _lang(KYC_PROMPT, lang),
            intent="BOOKING",
            buttons=[
                (KYC_WHATSAPP_ID, _label(KYC_SEND_LABEL, lang)),
                (KYC_HANDOVER_ID, _label(KYC_HANDOVER_LABEL, lang)),
            ],
        ))
        return True

    # ---------------- KYC ---------------- #
    if bid == KYC_WHATSAPP_ID:
        set_state(
            db, conversation_id, KYC_WAIT,
            car_code=data.get("car_code"), hours=data.get("hours"),
            drive=data.get("drive"), date=data.get("date"), time=data.get("time"),
            handover=data.get("handover"), address=data.get("address"),
            kyc_count=0,
        )
        await sink(Outgoing(
            text=_lang(KYC_WAITING, lang),
            intent="BOOKING",
            buttons=[("kyc_done", _label(KYC_DONE_LABEL, lang))],
        ))
        return True

    if bid == KYC_HANDOVER_ID:
        return await _finalize_summary(
            db, ctx, inbound, lang, sink, data, kyc_mode="handover")

    if bid == "kyc_done" or (step == KYC_WAIT and lowered in {
        "done", "ho gaya", "हो गया", "✅ done", "✅ हो गया",
    }):
        count = int(data.get("kyc_count") or 0)
        if step == KYC_WAIT and count == 0:
            await sink(Outgoing(
                text=_lang(KYC_WAITING, lang),
                intent="BOOKING",
                buttons=[("kyc_done", _label(KYC_DONE_LABEL, lang))],
            ))
            return True
        return await _finalize_summary(
            db, ctx, inbound, lang, sink, data, kyc_mode="whatsapp")

    if step in (KYC, KYC_WAIT) and has_media:
        count = int(data.get("kyc_count") or 0) + 1
        if count >= 2:
            await sink(Outgoing(
                text=_lang(KYC_DONE, lang),
                intent="BOOKING",
            ))
            return await _finalize_summary(
                db, ctx, inbound, lang, sink, data, kyc_mode="whatsapp")
        set_state(
            db, conversation_id, KYC_WAIT,
            car_code=data.get("car_code"), hours=data.get("hours"),
            drive=data.get("drive"), date=data.get("date"), time=data.get("time"),
            handover=data.get("handover"), address=data.get("address"),
            kyc_count=count,
        )
        await sink(Outgoing(
            text=_lang(KYC_ONE_RECEIVED, lang),
            intent="BOOKING",
            buttons=[("kyc_done", _label(KYC_DONE_LABEL, lang))],
        ))
        return True

    # ---------------- confirmation ---------------- #
    if bid == CONFIRM_BOOKING_ID:
        return await confirm_booking(db, ctx, inbound, lang, sink, deliver)

    # ---------------- free text ---------------- #
    if text:
        # An explicit "all cars / full fleet" request beats fuzzy name matching
        # ("full fleet" otherwise latches onto a car description word).
        if _wants_fleet_photos(lowered):
            vehicles = _listed(db)
            if vehicles:
                set_state(db, conversation_id, BROWSE, mode="all")
                await _send_car_list(
                    db, sink, lang, vehicles, heading="Our complete fleet")
                return True

        # A car name typed at any point ("thar", "creta ka rate?") opens its card.
        if not has_media:
            vehicle = matching_vehicle(db, text)
            question_like = bool(re.search(
                r"\b(price|rate|rent|kitna|kitne|cost|charge|deposit|available|booking)\b",
                lowered,
            ))
            if vehicle is not None and (len(text) < 60 or question_like):
                set_state(
                    db, conversation_id, DURATION,
                    car_code=vehicle.code, scope="all",
                )
                await _send_car_card(db, sink, vehicle, lang, "all")
                return True

        if _greeting(lowered) and step in {"", WELCOME, MENU}:
            set_state(db, conversation_id, MENU)
            await sink(_main_menu(lang, returning=True))
            return True

        if re.search(r"\b(book|rent|reserve|chahiye|booking)\b", lowered) and \
                step in {"", WELCOME, MENU}:
            set_state(db, conversation_id, MENU)
            await sink(_browse_outgoing(lang))
            return True

        if step == NAME:
            await sink(Outgoing(
                text=_lang(NAME_NOT_FOUND, lang),
                intent="VEHICLE_SEARCH",
                interactive_list=list_payload(
                    _category_rows(db), "Browse the fleet"),
            ))
            set_state(db, conversation_id, BROWSE, mode="category")
            return True

    return False


async def _accept_time(
    db: DBSession, ctx, inbound, lang: str, sink: Sink,
    data: dict[str, Any], clock: time,
) -> bool:
    hours = int(data.get("hours") or 0)
    next_data = dict(data)
    next_data["time"] = clock.strftime("%H:%M")
    slot = _slot(next_data, hours)
    if slot is None:
        await sink(Outgoing(
            text=_lang(DATE_INVALID, lang),
            intent="BOOKING",
            buttons=[
                (DATE_TODAY_ID, _label(DATE_TODAY, lang)),
                (DATE_TOMORROW_ID, _label(DATE_TOMORROW, lang)),
            ],
        ))
        set_state(db, ctx.conversation.id, PICK_DATE, **{
            k: v for k, v in data.items() if k != "time"
        })
        return True
    start, end = slot
    problem = _slot_problem(start, end)
    if problem:
        friendly = (
            "That time has already passed today 🙏 Please pick a later time or choose Tomorrow."
            if "past" in problem else
            "That's a little too soon for us to prepare the car 🙏 Please pick a later time today "
            "or choose Tomorrow."
        )
        await sink(Outgoing(
            text=friendly,
            intent="BOOKING",
            interactive_list=list_payload(time_rows(lang), "Pick a time"),
        ))
        set_state(
            db, ctx.conversation.id, PICK_TIME,
            car_code=data.get("car_code"), hours=data.get("hours"),
            drive=data.get("drive"), date=data.get("date"),
        )
        return True

    set_state(
        db, ctx.conversation.id, HANDOVER,
        car_code=data.get("car_code"), hours=data.get("hours"),
        drive=data.get("drive"), date=data.get("date"),
        time=next_data["time"],
    )
    await sink(_handover_outgoing(lang))
    return True


def _greeting(text: str) -> bool:
    return bool(re.search(
        r"^\s*(hi+|hello+|hey+|hlo|namaste|namaskar|help|menu|start|main menu)\b",
        text or "",
    ))


def _wants_fleet_photos(text: str) -> bool:
    """Asking for photos opens the swipeable fleet carousel, never a photo dump."""
    return bool(re.search(
        r"(all (the )?(images|photos|pictures|pics|cars|vehicles)|"
        r"full (car )?fleet|entire fleet|whole fleet|show me (the )?fleet|"
        r"gallery|fleet photos|"
        r"saari (photos|images|gaadiyan)|sab (photos|images)|"
        r"^images?$|^photos?$|^pictures?$|^album$|^gaadiyan$)",
        text or "",
    ))


def main_menu_outgoing(lang: str, returning: bool = False) -> Outgoing:
    return _main_menu(lang, returning=returning)


def _category_rows(db: DBSession) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    for v in _listed(db):
        key = (v.category or "Other").strip()
        counts[key] = counts.get(key, 0) + 1
    names = [c for c in CATEGORY_ORDER if c in counts] + [
        c for c in counts if c not in CATEGORY_ORDER
    ]
    return [
        list_row(CAT_PREFIX + _slug(name), name,
                 f"{counts[name]} car{'s' if counts[name] != 1 else ''}")
        for name in names[:MAX_ROWS]
    ]
