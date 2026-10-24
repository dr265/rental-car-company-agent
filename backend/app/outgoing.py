"""One outbound payload produced by a turn (shared by the agent and flow)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CarouselCard:
    """One swipeable WhatsApp carousel card (image + 3-line body + actions)."""

    image_id: str = ""
    image_url: str = ""
    body_text: str = ""
    buttons: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Outgoing:
    text: str
    intent: str = "GENERAL_ENQUIRY"
    buttons: list[tuple[str, str]] | None = None
    interactive_list: dict | None = None
    carousel: list[CarouselCard] | None = None
    image_url: str = ""
    image_id: str = ""
    image_caption: str = ""
    image_fallback_text: str = ""
    carry_options: list[str] = field(default_factory=list)
    delivery: tuple[str, str] = ("", "")
    images: list[dict] | None = None
