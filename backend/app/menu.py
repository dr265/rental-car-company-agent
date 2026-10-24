"""ZoomRideXX WhatsApp flow: copy, buttons, lists and small formatting helpers.

The customer journey is deliberately step-by-step:

    1. language          English / हिंदी
    2. browse cars       Category · Duration · Name · All Cars · Rules · Desk
    3. pick a car        list (≤10 rows), or the all-cars carousel
    4. car card          photo + 6h/12h/24h rates + Previous/Next car
    5. package           tap a rate on the card → choose the exact hours
    6. drive mode        Self-Drive / With Chauffeur
    7. pickup schedule   date → time → Hub Self-Pickup / Doorstep Delivery
    8. digital KYC       licence + ID on WhatsApp, or show at handover
    9. summary           vehicle, duration, mode, delivery, schedule, rent,
                         refundable deposit, cleanliness guarantee → Confirm
   10. confirmation      reference, handover message, owner alert

Every string is written as a real WhatsApp message, not a demo placeholder.
Ids are deterministic so a tap can always be matched to the step that sent it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session as DBSession

IST = timezone(timedelta(hours=5, minutes=30))


def local_time(dt) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST)
    return dt.strftime("%d %b %Y, %I:%M %p").replace(" 0", " ")

SHOP_NAME = "ZoomRideXX Car Rentals"
SHOP_SHORT = "ZoomRideXX"
TAGLINE = "Driven by comfort, Trusted for cleanliness."
DESK_NUMBERS = ("+91 91796 42928", "+91 95161 08857")
DESK_PHONES = ("9179642928", "9516108857")
DESK_HOURS = "8:00 AM – 10:00 PM, all days"
HUB_ADDRESS = "ZoomRideXX Hub (share your location on WhatsApp and we'll send the pin)"

MAX_ROWS = 10
MAX_TITLE = 24
MAX_DESCRIPTION = 72

# --------------------------------------------------------------------------- #
# deterministic ids
# --------------------------------------------------------------------------- #
MENU_PREFIX = "menu_"
MENU_BOOK_CAR_ID = "menu_book_car"
MENU_DEPOSIT_KYC_ID = "menu_deposit_kyc"
MENU_CALL_DESK_ID = "menu_call_desk"
MENU_HOME_ID = "menu_home"
MENU_LANG_ID = "menu_lang"
MENU_MY_BOOKINGS_ID = "menu_my_bookings"
MENU_STAFF_ID = "menu_staff"
MENU_QUERY_ID = "menu_query"

BROWSE_CATEGORY_ID = "browse_category"
BROWSE_DURATION_ID = "browse_duration"
BROWSE_NAME_ID = "browse_name"
BROWSE_ALL_ID = "browse_all_cars"
PREV_CAR_ID = "prev_car"
NEXT_CAR_ID = "next_car"

CAT_PREFIX = "cat_"
CAR_PREFIX = "car_"
CAR_BOOK_PREFIX = "bookcar_"
CAR_VIEW_PREFIX = "viewcar_"
DUR_PREFIX = "dur_"
DRIVE_SELF_ID = "drive_self"
DRIVE_CHAUFFEUR_ID = "drive_chauffeur"
DATE_TODAY_ID = "date_today"
DATE_TOMORROW_ID = "date_tomorrow"
TIME_PREFIX = "time_"
HANDOVER_HUB_ID = "handover_hub"
HANDOVER_DOOR_ID = "handover_door"
KYC_WHATSAPP_ID = "kyc_whatsapp"
KYC_HANDOVER_ID = "kyc_handover"
CONFIRM_BOOKING_ID = "confirm_booking"
START_OVER_ID = "start_over"

# --------------------------------------------------------------------------- #
# copy
# --------------------------------------------------------------------------- #
INTRO: dict[str, str] = {
    "en": (
        f"Welcome to *{SHOP_NAME}* 🚗\n\n"
        "We rent well-maintained self-drive and chauffeur-driven cars on a simple "
        "6-hour, 12-hour or 24-hour package. Tell us what you need and we'll take "
        "care of the rest.\n\n"
        f"_{TAGLINE}_\n\n"
        "Please choose your language to get started."
    ),
    "hi": (
        f"*{SHOP_NAME}* में आपका स्वागत है 🚗\n\n"
        "हम 6 घंटे, 12 घंटे और 24 घंटे के पैकेज पर self-drive और chauffeur वाली "
        "गाड़ियाँ देते हैं। आप बताइए, बाकी हम संभाल लेंगे।\n\n"
        f"_{TAGLINE}_\n\n"
        "शुरू करने के लिए भाषा चुनिए।"
    ),
}

LANG_CONFIRM: dict[str, str] = {
    "en": "English it is 😊",
    "hi": "ठीक है, हिंदी में बात करते हैं 😊",
}

BROWSE_INTRO: dict[str, str] = {
    "en": (
        "*Browse Cars* 🚗\n\n"
        "Pick how you'd like to see the fleet. Every car opens with its photo and "
        "its exact 6-hour, 12-hour and 24-hour rates."
    ),
    "hi": (
        "*Browse Cars* 🚗\n\n"
        "देखिए कि fleet कैसे देखनी है। हर गाड़ी की फोटो और 6, 12, 24 घंटे का "
        "सही किराया साथ दिखेगा।"
    ),
}

BROWSE_RETURNING: dict[str, str] = {
    "en": "Back to the fleet 🚗 Where would you like to go?",
    "hi": "फिर fleet पर आ गए 🚗 कहाँ जाना है?",
}

CATEGORY_INTRO: dict[str, str] = {
    "en": "Pick a category and I'll show you the cars available in it.",
    "hi": "Category चुनिए, मैं उसकी उपलब्ध गाड़ियाँ दिखा देता हूँ।",
}

DURATION_INTRO: dict[str, str] = {
    "en": "Which package works for you? I'll show the cars and their exact price for that duration.",
    "hi": "आपको कौन सा पैकेज ठीक रहेगा? मैं उसी दर पर गाड़ियाँ और उनका किराया दिखा दूँगा।",
}

FLEET_CAROUSEL_INTRO: dict[str, str] = {
    "en": (
        "Here's our complete car fleet for you 🚗\n"
        "Swipe through the cards for photos, rates and key details."
    ),
    "hi": (
        "ये रही हमारी पूरी car fleet 🚗\n"
        "Cards swipe करके फोटो, किराया और details देखिए।"
    ),
}

CAR_BOOK_LABEL: dict[str, str] = {"en": "Book Now", "hi": "बुक करें"}
CAR_VIEW_LABEL: dict[str, str] = {"en": "View Details", "hi": "विवरण देखें"}

NAME_PROMPT: dict[str, str] = {
    "en": "Sure — type the car name you'd like (for example *Thar*, *Creta* or *Dzire*).",
    "hi": "ज़रूर — गाड़ी का नाम लिखिए (जैसे *Thar*, *Creta* या *Dzire*)।",
}

NAME_NOT_FOUND: dict[str, str] = {
    "en": (
        "I couldn't find a car by that name in our fleet 🙏 Here's the full list — "
        "tap the one you meant, or type another name."
    ),
    "hi": (
        "उस नाम की गाड़ी हमारे fleet में नहीं मिली 🙏 नीचे पूरी लिस्ट है — जो चाहिए "
        "उस पर टैप कीजिए, या दूसरा नाम लिखिए।"
    ),
}

CAR_CARD_HINT: dict[str, str] = {
    "en": "Tap a package to book, or use Previous / Next to see more cars.",
    "hi": "Book करने के लिए पैकेज चुनिए, या Previous / Next से दूसरी गाड़ियाँ देखिए।",
}

DRIVE_MODE_INTRO: dict[str, str] = {
    "en": (
        "*{car}* for *{hours} hours* — {price}.\n\n"
        "Would you like to drive yourself or have our chauffeur drive you?"
    ),
    "hi": (
        "*{car}*, *{hours} घंटे* — {price}।\n\n"
        "आप खुद चलाएँगे या हमारा chauffeur चलाएगा?"
    ),
}

DRIVE_SELF_LABEL: dict[str, str] = {
    "en": "🚗 Self-Drive",
    "hi": "🚗 खुद चलाऊँगा",
}
DRIVE_CHAUFFEUR_LABEL: dict[str, str] = {
    "en": "🧑‍✈️ With Chauffeur",
    "hi": "🧑‍✈️ Chauffeur के साथ",
}

CHAUFFEUR_NOTE: dict[str, str] = {
    "en": "Our chauffeur will be there for the whole package. The chauffeur charge is shown before you confirm.",
    "hi": "पूरे पैकेज के दौरान chauffeur साथ रहेगा। Confirm करने से पहले उसका चार्ज दिखा दिया जाएगा।",
}

DATE_PROMPT: dict[str, str] = {
    "en": (
        "When should we hand over the car?\n\n"
        "Tap *Today* or *Tomorrow*, or type the date (for example *25 Oct* or *25/10/2026*)."
    ),
    "hi": (
        "गाड़ी कब चाहिए?\n\n"
        "*आज* या *कल* पर टैप कीजिए, या तारीख लिखिए (जैसे *25 Oct* या *25/10/2026*)।"
    ),
}
DATE_TODAY: dict[str, str] = {"en": "Today", "hi": "आज"}
DATE_TOMORROW: dict[str, str] = {"en": "Tomorrow", "hi": "कल"}
DATE_INVALID: dict[str, str] = {
    "en": "I couldn't read that date 🙏 Please tap Today/Tomorrow or type a date like *25 Oct* or *25/10/2026*.",
    "hi": "तारीख समझ नहीं आई 🙏 आज/कल पर टैप कीजिए या *25 Oct* / *25/10/2026* जैसी तारीख लिखिए।",
}
DATE_PAST: dict[str, str] = {
    "en": "That date has already passed 🙏 Please choose today or a later date.",
    "hi": "यह तारीख निकल चुकी है 🙏 आज या उसके बाद की तारीख चुनिए।",
}

TIME_PROMPT: dict[str, str] = {
    "en": "What time should we hand over the car?",
    "hi": "गाड़ी किस समय चाहिए?",
}
TIME_INVALID: dict[str, str] = {
    "en": "Please pick a time from the list, or type a time like *10:30 am*.",
    "hi": "लिस्ट से समय चुनिए, या *10:30 am* जैसा समय लिखिए।",
}

HANDOVER_PROMPT: dict[str, str] = {
    "en": (
        "How would you like to collect the car?\n\n"
        "*Hub Self-Pickup* is free. *Doorstep Delivery* is ₹500 and our team brings "
        "the car to your address."
    ),
    "hi": (
        "गाड़ी कैसे लेना चाहेंगे?\n\n"
        "*Hub Self-Pickup* मुफ़्त है। *Doorstep Delivery* ₹500 का है — हमारी टीम गाड़ी "
        "आपके पते पर ले आएगी।"
    ),
}
HUB_LABEL: dict[str, str] = {"en": "🏢 Hub Self-Pickup", "hi": "🏢 Hub से खुद लें"}
DOOR_LABEL: dict[str, str] = {"en": "🏠 Doorstep Delivery", "hi": "🏠 घर पर डिलीवरी"}
ADDRESS_PROMPT: dict[str, str] = {
    "en": "Please send the full delivery address with a nearby landmark.",
    "hi": "कृपया पूरा पता और पास का landmark भेजिए।",
}
ADDRESS_INVALID: dict[str, str] = {
    "en": "Please send a little more detail — house/flat number, street and a nearby landmark.",
    "hi": "थोड़ा और विस्तार से भेजिए — मकान/फ्लैट नंबर, गली और पास का landmark।",
}

KYC_PROMPT: dict[str, str] = {
    "en": (
        "Last step — digital KYC 📄\n\n"
        "For self-drive we need:\n"
        "• Driving Licence — front and back\n"
        "• Aadhaar or Voter ID\n\n"
        "Send clear photos here on WhatsApp now, or show the originals at handover."
    ),
    "hi": (
        "आख़िरी step — digital KYC 📄\n\n"
        "Self-drive के लिए चाहिए:\n"
        "• Driving Licence — आगे और पीछे दोनों\n"
        "• Aadhaar या Voter ID\n\n"
        "अभी WhatsApp पर साफ़ फोटो भेजिए, या handover के समय original दिखा दीजिए।"
    ),
}
KYC_SEND_LABEL: dict[str, str] = {
    "en": "📷 Send photos now",
    "hi": "📷 अभी फोटो भेजूँ",
}
KYC_HANDOVER_LABEL: dict[str, str] = {
    "en": "🪪 Show at handover",
    "hi": "🪪 Handover पर दिखाऊँगा",
}
KYC_WAITING: dict[str, str] = {
    "en": "Please send the photos here as WhatsApp images — licence front, licence back, and your Aadhaar/Voter ID.",
    "hi": "कृपया WhatsApp पर फोटो भेजिए — licence आगे, licence पीछे, और Aadhaar/Voter ID।",
}
KYC_ONE_RECEIVED: dict[str, str] = {
    "en": "Got it, thank you 📄 Please send the remaining document photo(s) — or tap *Done* if everything is here.",
    "hi": "मिल गया, धन्यवाद 📄 बाकी दस्तावेज़ की फोटो भेजिए — या सब भेज दिया हो तो *Done* दबाइए।",
}
KYC_DONE: dict[str, str] = {
    "en": "Documents received, thank you ✅ Our team will verify them before handover.",
    "hi": "दस्तावेज़ मिल गए, धन्यवाद ✅ Handover से पहले हमारी टीम इन्हें verify करेगी।",
}
KYC_DONE_LABEL: dict[str, str] = {"en": "✅ Done", "hi": "✅ हो गया"}
KYC_AT_HANDOVER_NOTE: dict[str, str] = {
    "en": "No problem — please carry the originals and we'll verify them at handover.",
    "hi": "कोई बात नहीं — original साथ लाइए, handover पर verify कर लेंगे।",
}

RULES_TEXT: dict[str, str] = {
    "en": (
        "📄 *Deposit & KYC rules*\n\n"
        "*Refundable security deposit*\n"
        "• Hatchback & sedan — ₹3,000\n"
        "• Compact SUV & SUV — ₹5,000\n"
        "• Fortuner & Endeavour — ₹10,000\n"
        "The deposit is returned after the car is checked back in.\n\n"
        "*KYC for self-drive*\n"
        "• Driving Licence — front and back\n"
        "• Aadhaar or Voter ID\n"
        "Send clear photos on WhatsApp before pickup, or show the originals at handover.\n\n"
        "*Other rules*\n"
        "• Fuel is not included; return the car at the same fuel level.\n"
        "• 250 km included per 24 hours. Extra distance is ₹12/km.\n"
        "• Traffic challans and damage during the rental are the customer's responsibility.\n"
        "• Please return the car by the end time shown on your booking."
    ),
    "hi": (
        "📄 *Deposit और KYC नियम*\n\n"
        "*Refundable security deposit*\n"
        "• Hatchback और sedan — ₹3,000\n"
        "• Compact SUV और SUV — ₹5,000\n"
        "• Fortuner और Endeavour — ₹10,000\n"
        "गाड़ी check-in होने के बाद deposit वापस मिल जाता है।\n\n"
        "*Self-drive के लिए KYC*\n"
        "• Driving Licence — आगे और पीछे\n"
        "• Aadhaar या Voter ID\n"
        "Pickup से पहले WhatsApp पर साफ़ फोटो भेजिए, या handover पर original दिखाइए।\n\n"
        "*दूसरे नियम*\n"
        "• Fuel शामिल नहीं है; गाड़ी उतने ही fuel level पर लौटाइए।\n"
        "• हर 24 घंटे में 250 km शामिल। Extra distance ₹12/km।\n"
        "• Rental के दौरान challan और damage की ज़िम्मेदारी customer की है।\n"
        "• Booking में दिखाए गए end time तक गाड़ी लौटाइए।"
    ),
}

CALL_DESK_TEXT: dict[str, str] = {
    "en": (
        "📞 *Fleet desk*\n\n"
        f"Call us on {DESK_NUMBERS[0]} or {DESK_NUMBERS[1]}.\n"
        f"Open {DESK_HOURS}.\n\n"
        "If you're already chatting with us, you can also just tell me what you need "
        "and I'll pass it to the team."
    ),
    "hi": (
        "📞 *Fleet desk*\n\n"
        f"हमें {DESK_NUMBERS[0]} या {DESK_NUMBERS[1]} पर call कीजिए।\n"
        f"समय: {DESK_HOURS}.\n\n"
        "अगर आप यहीं chat कर रहे हैं तो मुझे बता दीजिए, मैं team तक पहुँचा दूँगा।"
    ),
}

NO_CARS: dict[str, str] = {
    "en": "That part of the fleet is being updated right now 🙏 Call our fleet desk and we'll confirm what's available.",
    "hi": "Fleet का यह हिस्सा अभी update हो रहा है 🙏 Fleet desk पर call कीजिए, हम availability confirm कर देंगे।",
}

ASK_QUERY: dict[str, str] = {
    "en": "Sure — type your question and I'll help. You can ask about a car, rates, documents, delivery or your booking.",
    "hi": "ज़रूर — अपना सवाल लिखिए। गाड़ी, किराया, documents, delivery या booking के बारे में पूछ सकते हैं।",
}

HELP_FOOTER: dict[str, str] = {
    "en": f"Need help? Call {DESK_NUMBERS[0]}.",
    "hi": f"मदद चाहिए? {DESK_NUMBERS[0]} पर call कीजिए।",
}

# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #
def _lang(lang: str, table: dict[str, str]) -> str:
    return table.get(lang) or table["en"]


def money(amount: float | int | None) -> str:
    return f"₹{float(amount or 0):,.0f}"


def browse_intro(lang: str, returning: bool = False) -> str:
    return _lang(lang, BROWSE_RETURNING if returning else BROWSE_INTRO)


def category_intro(lang: str) -> str:
    return _lang(lang, CATEGORY_INTRO)


def duration_intro(lang: str) -> str:
    return _lang(lang, DURATION_INTRO)


def name_prompt(lang: str) -> str:
    return _lang(lang, NAME_PROMPT)


def name_not_found(lang: str) -> str:
    return _lang(lang, NAME_NOT_FOUND)


def date_prompt(lang: str) -> str:
    return _lang(lang, DATE_PROMPT)


def time_prompt(lang: str) -> str:
    return _lang(lang, TIME_PROMPT)


def handover_prompt(lang: str) -> str:
    return _lang(lang, HANDOVER_PROMPT)


def address_prompt(lang: str) -> str:
    return _lang(lang, ADDRESS_PROMPT)


def kyc_prompt(lang: str) -> str:
    return _lang(lang, KYC_PROMPT)


def rules_text(lang: str) -> str:
    return _lang(lang, RULES_TEXT)


def call_desk_text(lang: str) -> str:
    return _lang(lang, CALL_DESK_TEXT)


def budget_note(vehicle) -> str:
    """One-line rate summary used in list rows and the car card."""
    bits = []
    for hours, value in ((6, vehicle.price_6h), (12, vehicle.price_12h), (24, vehicle.price_24h)):
        if value:
            bits.append(f"{hours}h {money(value)}")
    return " · ".join(bits)


def car_title(vehicle) -> str:
    return (vehicle.name or "Car")[:MAX_TITLE]


def car_row(vehicle, hours: int | None = None) -> dict[str, Any]:
    price = None
    if hours == 6:
        price = vehicle.price_6h
    elif hours == 12:
        price = vehicle.price_12h
    elif hours == 24:
        price = vehicle.price_24h
    description = (
        f"{hours}h · {money(price)} · {vehicle.fuel or 'fuel'} · {vehicle.seats or 5} seats"
        if price else budget_note(vehicle)
    )
    return {
        "id": CAR_PREFIX + (vehicle.code or "").lower(),
        "title": car_title(vehicle),
        "description": description[:MAX_DESCRIPTION],
        "code": vehicle.code,
    }


def duration_label(hours: int) -> str:
    return f"{hours} hours"


def car_card_text(vehicle, lang: str, position: str = "") -> str:
    title = f"*{vehicle.name}*"
    if position:
        title += f" · {position}"
    lines = [
        title,
        f"{vehicle.category or 'Car'} · {str(vehicle.fuel or '').title()} · "
        f"{str(vehicle.transmission or '').title()} · {vehicle.seats or 5} seats",
        "",
    ]
    if vehicle.price_6h:
        lines.append(f"• 6 hours — {money(vehicle.price_6h)}")
    if vehicle.price_12h:
        lines.append(f"• 12 hours — {money(vehicle.price_12h)}")
    if vehicle.price_24h:
        lines.append(f"• 24 hours — {money(vehicle.price_24h)}")
    lines.append("")
    lines.append(f"Refundable deposit: {money(vehicle.deposit)}")
    if vehicle.description:
        lines.append("")
        lines.append(vehicle.description)
    lines.append("")
    lines.append(_lang(lang, CAR_CARD_HINT))
    return "\n".join(lines)


def car_carousel_body(vehicle, lang: str = "en", hours: int | None = None) -> str:
    """Three-line card body that fits WhatsApp's 160-char / 2-line-break cap.

    A duration-specific fleet leads with that package's rate, so the card
    always matches the heading the customer tapped.
    """
    name = (vehicle.name or "Car")[:44]
    specs = " · ".join(part for part in (
        vehicle.category or "Car",
        str(vehicle.fuel or "").title(),
        str(vehicle.transmission or "").title(),
        f"{vehicle.seats or 5} seats",
    ) if part)[:72]
    catalog = {6: vehicle.price_6h, 12: vehicle.price_12h, 24: vehicle.price_24h}
    order = [12, 24, 6]
    if hours in catalog and catalog.get(hours):
        order = [hours] + [h for h in order if h != hours]
    rates = [
        f"{money(catalog[h])} / {h} {'घंटे' if lang == 'hi' else 'hrs'}"
        for h in order if catalog.get(h)
    ][:2]
    return "\n".join(line for line in (name, specs, " · ".join(rates)) if line)[:160]


def drive_mode_intro(lang: str, vehicle, hours: int, price: float) -> str:
    template = _lang(lang, DRIVE_MODE_INTRO)
    return template.format(car=vehicle.name, hours=hours, price=money(price))


def summary_text(lang: str, draft, vehicle, address: str = "") -> str:
    when = local_time(draft.start_at)
    mode = "With Chauffeur" if draft.with_driver else "Self-Drive"
    handover = "Doorstep Delivery" if draft.handover == "doorstep" else "Hub Self-Pickup"
    kyc = {
        "whatsapp": "Documents sent on WhatsApp",
        "handover": "Documents to be shown at handover",
    }.get(draft.kyc_mode or "", "Documents pending")
    lines = [
        "Here's your booking summary ✅",
        "",
        f"🚗 *{vehicle.name}*",
        f"⏱ {draft.duration_hours or draft.days} hours",
        f"🧑‍✈️ {mode}",
        f"📍 {handover}",
        f"🗓 {when}",
    ]
    if draft.handover == "doorstep" and address:
        lines.append(f"🏠 {address}")
    lines += [
        f"📄 {kyc}",
        "",
        f"Estimated rent: *{money(draft.total_estimate)}*",
    ]
    if draft.driver_fee:
        lines.append(f"(includes chauffeur {money(draft.driver_fee)})")
    if draft.delivery_fee:
        lines.append(f"(includes delivery {money(draft.delivery_fee)})")
    lines += [
        f"Refundable deposit: {money(draft.deposit)}",
        "",
        "🧼 Every ZoomRideXX car is cleaned and sanitised before handover. If anything "
        "isn't right at pickup, our team will fix it on the spot.",
        "",
        "Tap *Confirm Booking* to lock this in.",
    ]
    return "\n".join(lines)


def confirmed_text(lang: str, booking, vehicle) -> str:
    when = local_time(booking.start_at)
    mode = "With Chauffeur" if booking.with_driver else "Self-Drive"
    handover = "Doorstep Delivery" if booking.handover == "doorstep" else "Hub Self-Pickup"
    lines = [
        f"✅ *Booking confirmed — {booking.reference}*",
        "",
        f"🚗 {vehicle.name}",
        f"⏱ {booking.duration_hours or booking.days} hours · {mode}",
        f"📍 {handover}",
        f"🗓 {when}",
        f"💰 Estimated rent: {money(booking.total_estimate)}",
        f"🔁 Refundable deposit: {money(booking.deposit)}",
        "",
        "Our fleet desk will call you on this number shortly to confirm the handover "
        "details and share the exact pickup location.",
        "",
        "Please carry your original Driving Licence and Aadhaar/Voter ID. The car will "
        "be cleaned and sanitised before you receive it.",
        "",
        f"If you need anything, call {DESK_NUMBERS[0]}.",
    ]
    return "\n".join(lines)


def failure_text(lang: str, reason: str) -> str:
    if lang == "hi":
        return f"Booking पक्की नहीं हो सकी 🙏 — {reason}. हमारी team आपको call करके मदद करेगी।"
    return f"I couldn't lock the booking in 🙏 — {reason}. Our team will call you and sort it out."


def owner_alert_text(booking, vehicle, customer, address: str = "") -> str:
    when = local_time(booking.start_at)
    mode = "With Chauffeur" if booking.with_driver else "Self-Drive"
    handover = "Doorstep Delivery" if booking.handover == "doorstep" else "Hub Self-Pickup"
    name = customer.whatsapp_name or customer.name or "Customer"
    lines = [
        f"🔔 *New booking — {booking.reference}*",
        "",
        f"👤 {name} · {customer.display_phone or '+' + customer.phone}",
        f"🚗 {vehicle.name} ({vehicle.code})",
        f"⏱ {booking.duration_hours or booking.days} hours · {mode}",
        f"📍 {handover}",
        f"🗓 {when}",
        f"💰 Rent {money(booking.total_estimate)} · Deposit {money(booking.deposit)}",
    ]
    if address:
        lines.append(f"🏠 {address}")
    lines += [
        f"📄 KYC: {booking.kyc_mode or 'pending'}",
        "",
        "Please call the customer to confirm handover.",
    ]
    return "\n".join(lines)


def list_row(row_id: str, title: str, description: str = "") -> dict[str, str]:
    return {
        "id": row_id,
        "title": (title or "")[:MAX_TITLE],
        "description": (description or "")[:MAX_DESCRIPTION],
    }


def time_rows(lang: str) -> list[dict[str, str]]:
    rows = []
    for value in ("08:00", "10:00", "12:00", "14:00", "16:00", "18:00"):
        label = datetime.strptime(value, "%H:%M").strftime("%I:%M %p").lstrip("0")
        rows.append(list_row(TIME_PREFIX + value.replace(":", ""), label))
    return rows


def list_payload(rows: list[dict[str, str]], button: str = "") -> dict:
    return {
        "button": (button or "Choose an option")[:20],
        "header": "",
        "rows": [(r["id"], r["title"], r.get("description", "")[:MAX_DESCRIPTION])
                 for r in rows],
    }


def category_rows(categories: list[str], lang: str) -> list[dict[str, str]]:
    import re

    rows = []
    for name in categories[:MAX_ROWS]:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        rows.append(list_row(CAT_PREFIX + slug, name))
    return rows


def matching_vehicle(db: DBSession, text: str):
    """Find one car from free text (name, model word or code)."""
    from app.vehicles import find_vehicle, search_vehicles

    text = (text or "").strip()
    if not text:
        return None
    exact = find_vehicle(db, text)
    if exact is not None:
        return exact
    rows = search_vehicles(db, text, limit=5)
    if not rows:
        return None
    low = text.lower()
    for row in rows:
        if row.name.lower() in low or low in row.name.lower():
            return row
    name_words = [w for w in low.split() if len(w) > 2]
    for row in rows:
        if any(word in row.name.lower() for word in name_words):
            return row
    return rows[0] if len(rows) == 1 else None
