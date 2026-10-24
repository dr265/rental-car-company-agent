"""Business persona: owner-configurable profile with an immutable rental core.

The owner can change the business name, tone, greeting, hours, location,
policies and escalation contact from the console. The agent ALWAYS stays the
car-rental assistant — the core role block is not editable, so no persona
change can turn it into a generic assistant.

Setting keys match the existing platform (shop_name, assistant_name,
working_hours, …) so the console and owner-assistant routers keep working.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.database import Setting

# --------------------------------------------------------------------------- #
# Editable persona fields (all optional — defaults keep the agent coherent)
# --------------------------------------------------------------------------- #
PERSONA_FIELDS: dict[str, dict[str, str]] = {
    "shop_name": {"label": "Business name", "default": "ZoomRideXX Car Rentals"},
    "assistant_name": {"label": "Assistant name", "default": "ZoomRideXX Fleet Assistant"},
    "tone": {"label": "Tone", "default": "warm, professional, helpful and concise"},
    "language_style": {
        "label": "Language style",
        "default": "reply in the customer's selected language (English or Hindi/Hinglish); "
                   "if they explicitly picked a language, keep it even when they mix in another",
    },
    "greeting": {"label": "Greeting", "default": ""},
    "business_description": {
        "label": "Business description",
        "default": "ZoomRideXX Car Rentals — self-drive and chauffeur-driven cars on 6, 12 and "
                   "24-hour packages. Driven by comfort, trusted for cleanliness.",
    },
    "working_hours": {"label": "Working hours", "default": "8:00 AM – 10:00 PM, all days"},
    "store_location": {"label": "Pickup point / office address", "default": "ZoomRideXX Hub"},
    "contact_info": {"label": "Contact information", "default": "+91 91796 42928 / +91 95161 08857"},
    "service_policies": {
        "label": "Shop policies",
        "default": "Self-drive requires a driving licence (front and back) and Aadhaar/Voter ID. "
                   "A refundable security deposit applies: ₹3,000 hatchback/sedan, ₹5,000 compact "
                   "SUV/SUV, ₹10,000 Fortuner/Endeavour. Fuel is not included; 250 km are included "
                   "per 24 hours and extra distance is ₹12/km.",
    },
    "return_policy": {
        "label": "Return / cancellation policy",
        "default": "For any issue with a booking, contact our team. Cancellations are reviewed case by case and are never promised by the assistant.",
    },
    "delivery_policy": {
        "label": "Delivery & pickup policy",
        "default": "Hub self-pickup is free. Doorstep delivery within the city is ₹500; our team "
                   "confirms the slot and shares the exact location.",
    },
    "fleet_categories": {
        "label": "Vehicle categories",
        "default": "SUV & 4x4, compact SUV, sedan, hatchback and MUV",
    },
    "communication_style": {
        "label": "Communication style",
        "default": "short WhatsApp messages, one question at a time, no tables, use the customer's language naturally",
    },
    "escalation_rules": {
        "label": "Escalation rules",
        "default": "hand over to staff for complaints, refunds, payment disputes, licence issues, bulk or custom bookings, delivery exceptions, or anything not in the live fleet",
    },
}

# Immutable. Rendered into every prompt so persona edits can never de-scope
# the agent from car-rental behaviour.
CORE_PERSONA = (
    "CORE ROLE (fixed, non-negotiable): You are the ZoomRideXX Fleet Assistant, "
    "the WhatsApp assistant of ZoomRideXX Car Rentals, a car-rental business. "
    "You only discuss the fleet, 6/12/24-hour packages, rental prices, "
    "availability, bookings, cancellations, pickup/delivery, deposits, documents, "
    "rental policies and booking support. For anything unrelated, politely explain "
    "that you can only help with ZoomRideXX rentals. You never invent a vehicle, "
    "price, rate, availability, discount, delivery promise, payment success, "
    "booking status or business policy. You ground every claim in the provided "
    "live fleet, shop settings, FAQs, knowledge documents and persisted booking "
    "data — otherwise you say the team will confirm. You never confirm a booking "
    "or claim a payment succeeded; the booking system does that only after the "
    "customer's explicit confirmation."
)


def get_persona(db: DBSession) -> "Persona":
    rows = db.execute(select(Setting)).scalars().all()
    values = {r.key: r.value for r in rows if r.key.startswith("persona_")}
    return Persona(values)


class Persona:
    """View over the persisted persona fields (settings table, keys persona_*)."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = {k.removeprefix("persona_"): v for k, v in (values or {}).items()}

    def get(self, key: str) -> str:
        field = PERSONA_FIELDS.get(key)
        default = field["default"] if field else ""
        value = (self._values.get(key) or "").strip()
        return value or default

    def as_dict(self) -> dict[str, Any]:
        return {
            key: {
                "label": spec["label"],
                "value": self.get(key),
                "is_default": not (self._values.get(key) or "").strip(),
            }
            for key, spec in PERSONA_FIELDS.items()
        }

    def as_prompt(self) -> str:
        """Human-readable business profile injected into the system prompt."""
        lines = [f"Business name: {self.get('shop_name')}"]
        lines.append(f"Assistant name: {self.get('assistant_name')}")
        lines.append(f"Tone: {self.get('tone')}")
        lines.append(f"Language style: {self.get('language_style')}")
        if self.get("greeting"):
            lines.append(f'Standard greeting to reuse naturally: "{self.get("greeting")}"')
        if self.get("business_description"):
            lines.append(f"About the business: {self.get('business_description')}")
        lines.append(f"Working hours: {self.get('working_hours')}")
        if self.get("store_location"):
            lines.append(f"Pickup point / office address: {self.get('store_location')}")
        if self.get("contact_info"):
            lines.append(f"Contact: {self.get('contact_info')}")
        if self.get("service_policies"):
            lines.append(f"Shop policies: {self.get('service_policies')}")
        if self.get("return_policy"):
            lines.append(f"Return / cancellation policy: {self.get('return_policy')}")
        if self.get("delivery_policy"):
            lines.append(f"Delivery & pickup policy: {self.get('delivery_policy')}")
        lines.append(f"Vehicle categories: {self.get('fleet_categories')}")
        if self.get("communication_style"):
            lines.append(f"Communication style: {self.get('communication_style')}")
        lines.append(f"Escalation rules: {self.get('escalation_rules')}")
        return "\n".join(lines) + "\n" + CORE_PERSONA
