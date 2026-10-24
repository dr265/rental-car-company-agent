"""Multilingual support: English (default) and Hindi/Hinglish.

This module is the ONE source of truth for languages. The console selector, the
WhatsApp reply-buttons, the ``/api/languages`` endpoint, the prompt line and
every localized string read from ``SUPPORTED`` — adding a language here adds it
everywhere; nothing else in the project keeps a language list.

Design:
  • A customer's language is a durable fact stored in customer_memories
    (key = 'language') so it survives restarts and shows up in the owner's
    memory chips like any other fact. ``source`` records HOW it was chosen:
    'language selection' = the customer picked it (explicit, sticky) and
    'auto' = we detected it from a message. An explicit choice is never
    overridden by the language of a later message — only by the customer
    picking another language (button, selector or natural language request).
  • Detection is deterministic (script ranges + Hinglish markers) — no LLM
    call needed, works on the very first message.
  • The active language is injected into the system prompt; the LLM writes the
    reply in that language. Switching keeps the conversation, memory, persona
    and tools untouched — only the response language changes.
  • Button labels for interactive language selection live here too, so the
    WhatsApp experience and the console tester render the same choices.
"""
from __future__ import annotations

import re
from sqlalchemy.orm import Session as DBSession

from app.database import CustomerMemory

# Code → display metadata + prompt fragment + deterministic confirmations.
SUPPORTED: dict[str, dict[str, str]] = {
    "en": {
        "label": "English",
        "native": "English",
        "flag": "🇬🇧",
        "prompt": "English",
        "confirm": "English it is 😊",
    },
    "hi": {
        "label": "Hindi / Hinglish",
        "native": "हिंदी",
        "flag": "🇮🇳",
        "prompt": "Hindi (natural Hinglish in Latin script is fine, e.g. 'mujhe Creta ka rent batao'; "
                  "match the customer's mix of Hindi and English words)",
        "confirm": "ठीक है, हिंदी में बात करते हैं 😊",
    },
}

DEFAULT_LANGUAGE = "en"

# Provenance recorded on the stored preference row.
EXPLICIT_SOURCE = "language selection"   # customer chose it → sticky
AUTO_SOURCE = "auto-detected"            # we inferred it from a message

# Interactive language-selection buttons (WhatsApp reply buttons: title ≤ 20 chars).
LANGUAGE_BUTTONS: list[tuple[str, str]] = [
    ("lang_en", "English"),
    ("lang_hi", "हिंदी"),
]

LANG_BUTTON_PREFIX = "lang_"

# First-contact introduction per language ({assistant} / {shop} substituted).
INTRO: dict[str, str] = {
    "en": "Welcome to {shop}! 🚗 I'm {assistant}, your car-rental assistant. I can help you "
          "browse our fleet, check availability, get rental prices, and book a car — all on "
          "WhatsApp. Please pick your language to get started:",
    "hi": "{shop} में आपका स्वागत है! 🚗 मैं {assistant} हूँ, आपका car-rental assistant. "
          "Fleet देखने, availability check करने, rent बताने और car book करने में मदद करूँगा — "
          "सब WhatsApp पर. अपनी भाषा चुनिए:",
}

# Confirmation when the language changes through NATURAL LANGUAGE (not a button).
SWITCH_CONFIRM: dict[str, str] = {
    "en": "Sure! 🌐 I'll continue in English.",
    "hi": "ठीक है! 🌐 अब मैं हिंदी में बात करूँगा।",
}

# --------------------------------------------------------------------------- #
# image captions / clarifications (localized — requirement: captions follow the
# active conversation language)
# --------------------------------------------------------------------------- #
IMAGE_CAPTION: dict[str, str] = {
    "en": "Here is the {label} ✨",
    "hi": "यह रही {label} ✨",
}

IMAGE_NOT_FOUND: dict[str, str] = {
    "en": "I don't have that picture with me right now 🙏 — tell me the car name and "
          "I'll send its photo, or I'll ask the team to share it.",
    "hi": "इसकी तस्वीर अभी मेरे पास नहीं है 🙏 — गाड़ी का नाम बता दीजिए, मैं उसकी फोटो "
          "भेज दूँगा या टीम से भिजवा दूँगा।",
}

IMAGE_AMBIGUOUS: dict[str, str] = {
    "en": "I have more than one matching picture — which one should I send?\n{options}",
    "hi": "एक से ज़्यादा तस्वीरें मिल रही हैं — कौन सी भेजूँ?\n{options}",
}

IMAGE_UNAVAILABLE: dict[str, str] = {
    "en": "I found that picture but it can't be sent right now 🙏 Please try again in a moment.",
    "hi": "तस्वीर मिल गई लेकिन अभी भेजी नहीं जा सकी 🙏 कृपया थोड़ी देर बाद फिर कहें।",
}

# Sent ONCE per handoff window when a customer writes while the chat is with
# staff, so the wait is never silent (the owner still sees every message).
HANDOFF_WAIT: dict[str, str] = {
    "en": "Our team has your message 🙏 — someone will continue this chat here shortly.",
    "hi": "आपका मैसेज हमारी टीम को मिल गया है 🙏 — हम थोड़ी देर में यहीं जवाब देंगे।",
}


def label(lang: str) -> str:
    """Display label of a language code (falls back to English)."""
    return (SUPPORTED.get(lang) or SUPPORTED[DEFAULT_LANGUAGE])["label"]


def native_label(lang: str) -> str:
    spec = SUPPORTED.get(lang) or SUPPORTED[DEFAULT_LANGUAGE]
    return spec.get("native") or spec["label"]


def language_options() -> list[dict[str, str]]:
    """Registry for the UI selectors (console + WhatsApp buttons)."""
    return [
        {"code": code, "label": spec["label"], "native": spec.get("native", spec["label"]),
         "flag": spec.get("flag", "")}
        for code, spec in SUPPORTED.items()
    ]


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Hinglish markers (Latin-script Hindi). Weighted: strong markers alone are
# enough, weak markers need two or more hits to avoid false positives on
# English words like 'ha' or romanised brand names.
_HINGLISH_STRONG = {
    # Grammatical / function words only. Car names and numbers are deliberately
    # neutral: an English sentence such as "What is the price of Creta?" must
    # not be answered in Hindi.
    "mujhe", "mujhko", "karna", "karni", "karne", "kardo", "kar do", "chahiye",
    "kripya", "namaste", "namaskar", "kitna", "kitne", "kaisa", "kaisi",
    "dikha", "dikhao", "batao", "batayein", "nahi", "nahin", "haan",
    "theek", "banaye", "banwana", "shaadi", "shaadhi", "bhej", "bhejo",
    "dena", "dijiye", "aap", "aapka", "aapki", "mera", "meri", "yeh",
}
_HINGLISH_WEAK = {
    "hai", "hain", "ka", "ki", "ke", "ko", "mein", "me", "aur", "bhi", "kya",
    "se", "liye", "wala", "wali", "koi", "sab", "acha", "achha", "thoda",
}

_WORD_RE = re.compile(r"[a-z]+", re.IGNORECASE)
# The Devanagari range is explicit: combining vowel signs / virama are not \w,
# so "[^\W_]+" would split हिंदी into unusable single characters.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u0900-\u097F\u0C00-\u0C7F]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def detect_language(text: str) -> str:
    """Best-effort natural detection: Devanagari → hi, Hinglish markers → hi,
    else English (the default)."""
    t = (text or "").strip()
    if not t:
        return DEFAULT_LANGUAGE
    if _DEVANAGARI_RE.search(t):
        return "hi"
    words = [w.lower() for w in _WORD_RE.findall(t)]
    if not words:
        return DEFAULT_LANGUAGE
    strong = sum(1 for w in words if w in _HINGLISH_STRONG)
    weak = sum(1 for w in words if w in _HINGLISH_WEAK)
    if strong >= 1 and (strong + weak) >= 2:
        return "hi"
    if strong == 0 and weak >= 3:
        return "hi"
    return DEFAULT_LANGUAGE


# --------------------------------------------------------------------------- #
# explicit "speak in <language>" requests (natural-language switching)
# --------------------------------------------------------------------------- #
# Every spelling of a language we recognise, mapped to its code. Includes
# inflected forms used in real requests ("हिंदी में", "hindi me").
_LANGUAGE_NAMES: dict[str, str] = {
    # English / Hinglish
    "english": "en", "eng": "en", "angrezi": "en", "अंग्रेज़ी": "en", "अंग्रेजी": "en",
    "इंग्लिश": "en", "इंग्लिश में": "en",
    "hindi": "hi", "hindhi": "hi", "hinglish": "hi", "हिंदी": "hi", "हिन्दी": "hi",
    "हिंदी में": "hi", "हिन्दी में": "hi", "हिंदी मे": "hi", "हिंदी में ही": "hi",
    # multi-word latin forms are matched after joining tokens
    "hindi me": "hi", "hindi mein": "hi", "hindi mai": "hi", "in hindi": "hi",
    "in english": "en", "english me": "en", "english mein": "en", "english lo": "en",
}

# Words that turn a language mention into a deliberate switch request.
_SWITCH_CUES: set[str] = {
    "speak", "speaking", "switch", "change", "talk", "chat", "reply", "respond",
    "use", "only", "prefer", "please", "from", "now", "continue", "answer",
    "baat", "bolo", "bol", "karo", "kariye", "badlo", "jawab", "thoda",
    "बात", "बोलो", "बोलिए", "बोलना", "करो", "करें", "कीजिए", "बदलो", "जवाब", "में", "मे",
}


def detect_language_request(text: str) -> str | None:
    """Code when the message explicitly asks to switch language, else None.

    Examples that match: "Speak in Hindi.", "अब हिंदी में बात करो।",
    "switch to English", "hindi", "english mein".
    """
    raw = (text or "").strip()
    if not raw or len(raw) > 160:
        return None
    tokens = _tokens(raw)
    if not tokens:
        return None

    code = None
    for size in (3, 2, 1):
        for i in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[i:i + size])
            if phrase in _LANGUAGE_NAMES:
                code = _LANGUAGE_NAMES[phrase]
                break
        if code:
            break
    if code is None or code not in SUPPORTED:
        return None

    if any(t in _SWITCH_CUES for t in tokens):
        return code
    # A bare language name ("hindi") is a selection too — but only when the
    # message is short and is not asking for a picture.
    from app.media import is_image_request  # local import avoids a cycle

    if len(tokens) <= 3 and not is_image_request(raw):
        return code
    return None


# --------------------------------------------------------------------------- #
# per-customer persistence (CustomerMemory key='language')
# --------------------------------------------------------------------------- #
def _row(db: DBSession, customer_id: str) -> CustomerMemory | None:
    return db.query(CustomerMemory).filter(
        CustomerMemory.customer_id == customer_id,
        CustomerMemory.key == "language",
    ).first()


def get_language(db: DBSession, customer_id: str) -> str | None:
    row = _row(db, customer_id)
    value = (row.value if row else "") or ""
    return value if value in SUPPORTED else None


def get_language_source(db: DBSession, customer_id: str) -> str:
    """'' | 'language selection' (explicit) | 'auto-detected'."""
    row = _row(db, customer_id)
    return (row.source if row else "") or ""


def is_explicit(db: DBSession, customer_id: str) -> bool:
    return get_language_source(db, customer_id) == EXPLICIT_SOURCE


def set_language(
    db: DBSession, customer_id: str, lang: str, source: str = EXPLICIT_SOURCE,
) -> None:
    """Persist the active language. Only language state is touched — the
    conversation, memory, persona and tasks are never reset by a switch."""
    if lang not in SUPPORTED:
        return
    row = _row(db, customer_id)
    if row is None:
        db.add(CustomerMemory(customer_id=customer_id, key="language", value=lang,
                              source=source, confidence=1.0))
    else:
        row.value = lang
        row.source = source
    db.flush()


def language_for_message(db: DBSession, customer_id: str, text: str) -> tuple[str, bool]:
    """Resolve the language for this turn: explicit selection > detection.

    Returns (language_code, switched). Order of precedence:
      1. an explicit "speak in X" request in the message (natural-language switch)
      2. an explicit earlier selection (sticky — a message written in another
         language does NOT override it; requirement: selection wins)
      3. fresh detection for customers who never picked a language
    """
    requested = detect_language_request(text)
    stored = get_language(db, customer_id)
    if requested:
        return requested, requested != stored
    if stored is None:
        detected = detect_language(text)
        return detected, True
    if is_explicit(db, customer_id):
        # the customer's pick wins; only their own explicit change moves it
        return stored, False
    detected = detect_language(text)
    if detected != stored:
        return detected, True
    return stored, False


def prompt_line(lang: str, *, explicit: bool = False) -> str:
    """Instruction block injected into the system prompt for this turn."""
    spec = SUPPORTED.get(lang) or SUPPORTED[DEFAULT_LANGUAGE]
    mirror = (
        "The customer explicitly selected this language: keep replying in it even "
        "if their message is written in another language, until they change the "
        "language themselves. This overrides the persona's general language-style "
        "line and the language of the latest message."
        if explicit else
        "If the customer writes in a different language than this line says, follow "
        "the customer instead."
    )
    return (
        f"CUSTOMER LANGUAGE: {spec['prompt']}. Write the reply and every ui_options "
        f"label in this language. Keep proper nouns, product SKUs, prices, code, file "
        f"paths, commands and numbers exactly as they are — never translate identifiers. "
        f"{mirror}"
    )


def intro_text(lang: str, assistant_name: str, shop_name: str) -> str:
    return (INTRO.get(lang) or INTRO[DEFAULT_LANGUAGE]).format(
        assistant=assistant_name, shop=shop_name)


def switch_confirm(lang: str) -> str:
    return SWITCH_CONFIRM.get(lang) or SWITCH_CONFIRM[DEFAULT_LANGUAGE]


def image_caption(lang: str, image_label: str) -> str:
    template = IMAGE_CAPTION.get(lang) or IMAGE_CAPTION[DEFAULT_LANGUAGE]
    return template.format(label=image_label)


def image_not_found(lang: str) -> str:
    return IMAGE_NOT_FOUND.get(lang) or IMAGE_NOT_FOUND[DEFAULT_LANGUAGE]


def image_ambiguous(lang: str, options: list[str]) -> str:
    template = IMAGE_AMBIGUOUS.get(lang) or IMAGE_AMBIGUOUS[DEFAULT_LANGUAGE]
    numbered = "\n".join(f"{i}. {name}" for i, name in enumerate(options, 1))
    return template.format(options=numbered)


def image_unavailable(lang: str) -> str:
    return IMAGE_UNAVAILABLE.get(lang) or IMAGE_UNAVAILABLE[DEFAULT_LANGUAGE]


def handoff_wait_text(lang: str) -> str:
    return HANDOFF_WAIT.get(lang) or HANDOFF_WAIT[DEFAULT_LANGUAGE]
