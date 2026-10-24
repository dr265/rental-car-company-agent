"""Images the agent can actually SEND to a customer (registry + safe resolution).

Why this module exists
----------------------
WhatsApp/Meta cannot read a local file system. A message can only carry an
image as (a) a PUBLIC http(s) link that Meta fetches itself, or (b) a media id
obtained by uploading the bytes to the Cloud API. Handing the LLM (or the
owner) an absolute Windows path such as ``D:\\Project\\images\\logo.png``
therefore never delivers a picture — and hard-coding such paths breaks the
moment the app is packaged, moved or deployed.

So images are addressed by a REGISTRY ID and stored inside the project:

    backend/assets/images/swift-white.png           → id: swift-white
    <data>/uploads/images/<console upload>.png      → id: <slug>          (writable)

Resolution flow (no path ever comes from user text):

    request text → tokenise (English / Hindi) → topic + term scoring
      → 0 matches      → caller falls back to the fleet row's own photo
      → 1 clear winner → validate → send actual image + localized caption
      → a tie          → ask which one (never guess), remember the shortlist

Every id maps to a file inside a known root; ``..``/absolute paths and unknown
ids are rejected, and every file is validated (exists, readable, size, real
image bytes, PNG/JPEG/WEBP) before it is offered to the transport.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.config import (
    ASSETS_IMAGE_DIR,
    MAX_IMAGE_BYTES,
    MEDIA_DIRECT_UPLOAD,
    MEDIA_PUBLIC_BASE_URL,
    MEDIA_UPLOAD_DIR,
    MEDIA_URL_PATH,
    PUBLIC_BASE_URL,
)

log = logging.getLogger("rental.media")

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")
EXTENSION_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# Curated, portable registry: image id → file name inside backend/assets/images.
# The rental agent keeps this map EMPTY: every image in assets/images (or
# uploaded from the console) is picked up automatically by the directory scan,
# labelled from its file name, and matched by the vehicle topic words below —
# no absolute paths anywhere, nothing to rewrite when the project moves or is
# packaged into a desktop .exe.
IMAGE_MAP: dict[str, str] = {
}

# Human labels shown in the console + used in localized captions (optional
# overrides; the default label is the file name with dashes as spaces).
LABELS: dict[str, str] = {
    # The live ZoomRideXX fleet. Labels are shown to the CUSTOMER in the photo
    # caption, so they name the car only — never words like "photo".
    "thar-roxx": "Mahindra Thar Roxx",
    "thar-4x4": "Mahindra Thar 4x4",
    "scorpio-n": "Mahindra Scorpio N",
    "scorpio-s11": "Mahindra Scorpio S11",
    "xuv-700": "Mahindra XUV 700",
    "endeavour": "Ford Endeavour",
    "fortuner": "Toyota Fortuner",
    "ertiga": "Maruti Ertiga",
    "fronx": "Maruti Fronx",
    "dzire": "Maruti Dzire",
    "baleno": "Maruti Baleno",
    "swift": "Maruti Swift",
    "aura": "Hyundai Aura",
    "brezza": "Maruti Brezza",
    "creta": "Hyundai Creta",
    "verna": "Hyundai Verna",
    "venue": "Hyundai Venue",
}

# Photos that are NOT this fleet (stock/promotional shots supplied for look and
# feel). They are only ever sent when the customer names that make — never on a
# vague "show me a sedan" — so the agent can never pass a stock render off as
# the car the customer is about to pay for. Remove an id from this set (or add
# a plate to the file name) once a real photo of that car is in the registry.
PROMO_IMAGE_IDS: set[str] = set()

# Extra search terms ("aliases") per id, in every supported language. Optional
# — add an entry only when a specific photo needs extra words to be found.
ALIASES: dict[str, tuple[str, ...]] = {
    # Common spellings / Hinglish names customers actually type.
    "thar-roxx": ("tharrox", "thar rox", "rox", "new thar"),
    "thar-4x4": ("thar", "thar 4x4", "4x4 thar", "mahindra thar"),
    "scorpio-n": ("scorpio n", "scorpion", "new scorpio"),
    "scorpio-s11": ("scorpio s11", "s11", "old scorpio"),
    "xuv-700": ("xuv700", "xuv 700", "xuv"),
    "endeavour": ("endeavor", "ford endeavour", "ford endeavor"),
    "fortuner": ("toyota fortuner", "forturner"),
    "ertiga": ("maruti ertiga", "ertiga 7 seater"),
    "fronx": ("maruti fronx",),
    "dzire": ("desire", "maruti dzire"),
    "baleno": ("maruti baleno",),
    "swift": ("maruti swift",),
    "aura": ("hyundai aura",),
    "brezza": ("vitara brezza", "maruti brezza"),
    "creta": ("hyundai creta",),
    "verna": ("hyundai verna",),
    "venue": ("hyundai venue",),
}

# topic → the words that mean it, across the supported languages (English,
# Hindi/Hinglish). Keeps one scoring pass language-agnostic.
TOPIC_WORDS: dict[str, set[str]] = {
    "car": {
        "car", "cars", "gaadi", "gaari", "gadi", "vehicle", "vehicles",
        "rent", "rental", "rentals", "vahan",
        "गाड़ी", "कार", "वाहन",
    },
    "suv": {
        "suv", "suvs", "4x4", "thar", "scorpio", "xuv", "endeavour",
        "fortuner", "creta", "brezza", "venue", "seltos", "nexon",
        "harrier", "safari", "bolero",
    },
    "compact_suv": {
        "compact", "brezza", "venue", "nexon", "fronx", "punch",
        "magnite", "kiger",
    },
    "sedan": {
        "sedan", "sedans", "dzire", "verna", "city", "slavia", "virtus",
        "ciaz", "camry", "accord",
    },
    "hatchback": {
        "hatchback", "hatchbacks", "swift", "baleno", "aura", "i20",
        "wagonr", "wagon", "alto", "kwid", "tiago", "polo",
    },
    "muv": {
        "muv", "mpv", "ertiga", "innova", "crysta", "xl6", "marazzo",
        "triber", "7 seater", "7-seater",
    },
    "luxury": {
        "luxury", "premium", "bmw", "audi", "benz", "mercedes",
    },
    "tempo": {
        "tempo", "traveller", "van", "minibus", "bus",
    },
    "bike": {
        "bike", "bikes", "motorcycle", "scooter", "activa", "jupiter",
        "pulsar", "bullet", "royal", "enfield",
        "बाइक", "स्कूटर",
    },
    "logo": {"logo", "brand", "board", "signboard"},
}

TOPIC_OF: dict[str, set[str]] = {}
for _topic, _words in TOPIC_WORDS.items():
    for _w in _words:
        TOPIC_OF.setdefault(_w, set()).add(_topic)

# A customer "asking for a picture" in any supported language. Verbs
# (send/show/share) AND picture nouns count — nouns alone are enough, since
# "dashboard photo?" is a request in every language.
IMAGE_REQUEST_WORDS: set[str] = {
    # English
    "show", "send", "share", "pic", "pics", "photo", "photos", "image",
    "images", "picture", "pictures", "screenshot", "screenshots", "snapshot",
    "visual", "see", "look", "mail", "whatsapp",
    # Hindi / Hinglish
    "भेजो", "भेज", "भेजें", "भेजना", "भेजिए", "दिखाओ", "दिखा", "दिखाएं",
    "दिखाइए", "तस्वीर", "तस्वीरें", "फोटो", "चित्र", "इमेज", "फ़ोटो",
    "bhejo", "bhej", "dikhao", "dikha", "dikhaiye", "tasveer", "photo",
}

# Word tokens for English AND Devanagari. The Devanagari range is spelled out
# because combining vowel signs / virama are NOT \w in Python, which would
# shatter "झुमका" into single-letter pieces.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u0900-\u097F]+")


def _tokens(text: str) -> set[str]:
    return {
        t.lower() for t in _TOKEN_RE.findall(text or "")
        if t.isdigit() or len(t) > 1   # keep "2" for "send the 2nd one"
    }


def is_image_request(text: str) -> bool:
    """True when the message asks to see/receive a picture (any language)."""
    return bool(_tokens(text) & IMAGE_REQUEST_WORDS)


# --------------------------------------------------------------------------- #
# entries + validation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MediaImage:
    id: str
    filename: str
    label: str
    rel: str          # "assets/<file>" | "uploads/<file>" (URL path below /media)
    path: Path
    source: str       # assets | uploads
    size: int
    mime: str
    terms: frozenset[str]
    own: frozenset[str] = frozenset()   # concrete words; no topic expansion

    def as_dict(self, url: str = "") -> dict:
        """API/console view. Deliberately excludes the filesystem path — the
        console (and any client) addresses images by id or served URL only."""
        return {
            "id": self.id,
            "filename": self.filename,
            "label": self.label,
            "source": self.source,
            "size": self.size,
            "mime": self.mime,
            "url": url or public_url(self),
        }


def _own_terms(image_id: str, label: str) -> frozenset[str]:
    """The words that concretely NAME this image (file name, label, aliases).

    Kept separate from the topic-expanded set so promotional imagery can be
    held back from vague, category-level requests.
    """
    terms = _tokens(image_id.replace("-", " ")) | _tokens(label)
    terms |= {a.lower() for a in ALIASES.get(image_id, ())}
    for alias in ALIASES.get(image_id, ()):
        terms |= _tokens(alias)
    return frozenset(terms)


def _entry_terms(image_id: str, label: str) -> frozenset[str]:
    terms = set(_own_terms(image_id, label))
    # collapse to topics so "झुमका" matches "earrings-gold-drop"
    terms |= {topic for t in set(terms) for topic in TOPIC_OF.get(t, ())}
    return frozenset(terms)


def sniff_mime(path: Path) -> str:
    """Real MIME type from the file's magic bytes ('' when not an image)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return ""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def validate_image(path: Path, *, root: Path | None = None) -> tuple[bool, str]:
    """(ok, reason). Never raises — callers answer the customer gracefully."""
    try:
        if not path.exists():
            return False, "file missing"
        if not path.is_file():
            return False, "not a regular file"
        if root is not None and not _is_inside(path, root):
            return False, "outside the media directory"
        size = path.stat().st_size
        if size <= 0:
            return False, "empty file"
        if size > MAX_IMAGE_BYTES:
            return False, f"larger than {MAX_IMAGE_BYTES // (1024 * 1024)}MB"
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return False, f"unsupported format {path.suffix or '(none)'}"
        mime = sniff_mime(path)
        if not mime:
            return False, "not a readable PNG/JPEG/WEBP image"
        if mime != EXTENSION_MIME.get(path.suffix.lower()):
            return False, "file content does not match its extension"
        return True, ""
    except OSError as exc:
        return False, f"unreadable ({exc})"


# --------------------------------------------------------------------------- #
# registry lookup (ids only — user text never becomes a path)
# --------------------------------------------------------------------------- #
_ENTRY_CACHE: dict[str, tuple[float, tuple[MediaImage, ...]]] = {}
_CACHE_TTL = 5.0


def _safe_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:60]


# --------------------------------------------------------------------------- #
# fleet photos: the number plate is what makes it the RIGHT car
# --------------------------------------------------------------------------- #
# A rental fleet holds several cars of the SAME model (two Seltos, three
# Swifts), so a photo matched by model name alone is ambiguous — and sending
# the wrong car's picture to a customer is worse than sending none. The plate
# removes the ambiguity. It is recognised in the fleet row (code / name /
# description), in the image file name and in a console upload name, folded to
# bare upper-case characters and matched against each other:
#
#   fleet row  : description "Black KIA Seltos, AP39 HR 1004, 7 seats"
#   photo file : kia-seltos-ap39hr1004.jpg
#   → that row's photo every time, with nothing to configure in the console.
PLATE_RE = re.compile(
    r"\b([A-Z]{2}[\s\-]?\d{1,2}[\s\-]?[A-Z]{1,3}[\s\-]?\d{1,4})\b",
    re.IGNORECASE,
)


def _alnum(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def normalize_plate(value: str) -> str:
    """'ap 39 hr-1004' → 'AP39HR1004' ('' when the text is not a plate)."""
    text = _alnum(value)
    if not 7 <= len(text) <= 11:
        return ""
    if not text[:2].isalpha() or not any(c.isdigit() for c in text[2:]):
        return ""
    return text


def plate_of(*values: str) -> str:
    """First Indian-style registration number found in any of the values."""
    for value in values:
        match = PLATE_RE.search(value or "")
        if match:
            plate = normalize_plate(match.group(1))
            if plate:
                return plate
    return ""


def resolve_plate(plate: str) -> MediaImage | None:
    """The registry photo whose id or label carries this plate."""
    wanted = normalize_plate(plate)
    if not wanted:
        return None
    for entry in registry():
        if wanted in _alnum(entry.id) or wanted in _alnum(entry.label):
            return entry
    return None


def _entry_for(image_id: str, filename: str, source: str, root: Path) -> MediaImage | None:
    image_id = _safe_id(image_id)
    if not image_id:
        return None
    path = root / filename
    ok, _why = validate_image(path, root=root)
    if not ok:
        return None
    label = LABELS.get(image_id) or image_id.replace("-", " ")
    return MediaImage(
        id=image_id,
        filename=filename,
        label=label,
        rel=f"{source}/{filename}",
        path=path,
        source=source,
        size=path.stat().st_size,
        mime=sniff_mime(path),
        terms=_entry_terms(image_id, label),
        own=_own_terms(image_id, label),
    )


def registry(refresh: bool = False) -> tuple[MediaImage, ...]:
    """Every usable image: curated assets first, then console uploads.

    Robust to a missing folder, a corrupt file or a stray non-image — those are
    simply skipped, so one bad upload can never break the agent.
    """
    key = f"{ASSETS_IMAGE_DIR}|{MEDIA_UPLOAD_DIR}"
    now = time.time()
    if not refresh:
        cached = _ENTRY_CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]

    seen: set[str] = set()
    out: list[MediaImage] = []

    for image_id, filename in IMAGE_MAP.items():
        entry = _entry_for(image_id, filename, "assets", ASSETS_IMAGE_DIR)
        if entry and entry.id not in seen:
            seen.add(entry.id)
            out.append(entry)

    for root, source in ((ASSETS_IMAGE_DIR, "assets"), (MEDIA_UPLOAD_DIR, "uploads")):
        try:
            files = sorted(root.iterdir())
        except OSError:
            continue
        for item in files:
            if item.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            image_id = _safe_id(item.stem)
            if not image_id or image_id in seen:
                continue
            entry = _entry_for(image_id, item.name, source, root)
            if entry:
                seen.add(entry.id)
                out.append(entry)

    result = tuple(out)
    _ENTRY_CACHE[key] = (now, result)
    return result


def resolve(image_id: str, *, refresh: bool = False) -> MediaImage | None:
    """Registry-id lookup. Unknown ids and anything path-like return None."""
    wanted = _safe_id(image_id)
    if not wanted:
        return None
    for entry in registry(refresh=refresh):
        if entry.id == wanted:
            return entry
    return None


def library() -> list[dict]:
    return [e.as_dict() for e in registry()]


# --------------------------------------------------------------------------- #
# request → image resolution (scoring, never guessing)
# --------------------------------------------------------------------------- #
@dataclass
class Resolution:
    entry: MediaImage | None = None
    candidates: list[MediaImage] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = []

    @property
    def ambiguous(self) -> bool:
        return self.entry is None and len(self.candidates) > 1


def _score(entry: MediaImage, tokens: set[str], topics: set[str]) -> int:
    if entry.id in PROMO_IMAGE_IDS:
        # Stock/promotional imagery is only ever matched by its own NAME — a
        # brand word such as "honda" — never by a shared body type ("sedan",
        # "suv") nor by the words people use to ask for a picture ("show",
        # "send", "photo"), so a vague request can never surface it.
        distinctive = {
            t for t in entry.own
            if t not in TOPIC_OF and t not in IMAGE_REQUEST_WORDS
        }
        return len(distinctive & tokens)
    entry_topics = {t for term in entry.terms for t in TOPIC_OF.get(term, ())}
    return len(entry.terms & tokens) + 2 * len(entry_topics & topics)


def resolve_request(text: str) -> Resolution:
    """Best-matching registry image for a natural request in any language."""
    tokens = _tokens(text)
    if not tokens:
        return Resolution()
    # spelling tolerance: 'earings'/'jhumkaa' style typos and plurals
    expanded = set(tokens)
    for token in tokens:
        base = token.rstrip("s")
        if len(base) > 3:
            expanded.add(base)
        if len(token) > 4:
            expanded.add(token[:-1])
    topics = {t for token in expanded for t in TOPIC_OF.get(token, ())}

    scored: list[tuple[int, MediaImage]] = []
    for entry in registry():
        s = _score(entry, expanded, topics)
        if s > 0:
            scored.append((s, entry))
    if not scored:
        return Resolution()
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    top = scored[0][0]
    tied = [entry for s, entry in scored if s == top]
    if len(tied) == 1:
        return Resolution(entry=tied[0], candidates=tied)
    return Resolution(entry=None, candidates=tied[:3])


# --------------------------------------------------------------------------- #
# fleet row → photo (the ONE resolver shared by the agent and the console)
# --------------------------------------------------------------------------- #
def resolve_vehicle_image(
    ref: str = "", *, code: str = "", name: str = "", category: str = "",
    description: str = "",
) -> tuple[str, str]:
    """(public_url, registry_id) for one fleet row — ('','') when it has none.

    Resolution order, first hit wins:

      1. the row's own ``image_url`` when it is a public http(s) link
      2. the row's own ``image_url`` when it names a registry image id, so the
         console can point a vehicle straight at a shipped or uploaded photo
      3. the registration plate printed on the row (code / name / description)
         → that exact car's photo — the only reliable key when the fleet holds
         several cars of the same model
      4. a registry match on the model name
      5. a registry match on the category

    Never returns a filesystem path: WhatsApp cannot read one. Having a single
    resolver means the console preview and the message the customer actually
    receives can never disagree.
    """
    ref = (ref or "").strip()
    if ref.lower().startswith(("http://", "https://")):
        return ref, ""
    if ref:
        entry = resolve(ref)
        if entry is not None:
            return "", entry.id
    plate = plate_of(code, name, description)
    if plate:
        entry = resolve_plate(plate)
        if entry is not None:
            return "", entry.id
    for query in (name, category):
        if not query:
            continue
        resolution = resolve_request(query)
        if resolution.entry is not None:
            return "", resolution.entry.id
    return "", ""


def resolve_product_image(
    ref: str = "", *, code: str = "", name: str = "", category: str = "",
    description: str = "",
) -> tuple[str, str]:
    """Product-facing name for the same safe resolver.

    Keeping one implementation means the product card in the console and the
    photo attached on WhatsApp always point at the same registry id.
    """
    return resolve_vehicle_image(
        ref, code=code, name=name, category=category, description=description)


# --------------------------------------------------------------------------- #
# short-lived shortlist so "send the 2nd one" works after a clarification
# --------------------------------------------------------------------------- #
_PENDING: dict[str, tuple[float, list[str]]] = {}
_PENDING_TTL = 900.0
_ORDINALS = {
    "1": 0, "first": 0, "one": 0, "pehla": 0, "pehle": 0, "पहला": 0, "पहले": 0,
    
    "2": 1, "second": 1, "two": 1, "dusra": 1, "दूसरा": 1,
    "3": 2, "third": 2, "three": 2, "teesra": 2, "तीसरा": 2,
}


def remember_candidates(key: str, entries: list[MediaImage]) -> None:
    if not key:
        return
    _PENDING[key] = (time.time(), [e.id for e in entries])


def pick_pending(key: str, text: str) -> MediaImage | None:
    """Resolve a follow-up like "the second one" against the last shortlist."""
    if not key:
        return None
    row = _PENDING.get(key)
    if row is None:
        return None
    stored_at, ids = row
    if time.time() - stored_at > _PENDING_TTL:
        _PENDING.pop(key, None)
        return None
    tokens = _tokens(text)
    index = next((_ORDINALS[t] for t in tokens if t in _ORDINALS), None)
    if index is None:
        return None
    if index >= len(ids):
        return None
    entry = resolve(ids[index])
    if entry:
        _PENDING.pop(key, None)
    return entry


# --------------------------------------------------------------------------- #
# uploads (console "attach image")
# --------------------------------------------------------------------------- #
def save_upload(filename: str, data: bytes) -> tuple[MediaImage | None, str]:
    """Store uploaded bytes under the writable media dir with a safe name.

    The client filename is only used to derive a slug — the stored path is
    built here from a hash, so a crafted name can never escape the directory.
    """
    raw_name = Path(filename or "image").name
    suffix = Path(raw_name).suffix.lower()
    if suffix == ".jpe":
        suffix = ".jpg"
    if suffix not in SUPPORTED_EXTENSIONS:
        return None, f"unsupported format {suffix or '(none)'} — use PNG, JPG or WEBP"
    if not data:
        return None, "empty upload"
    if len(data) > MAX_IMAGE_BYTES:
        return None, f"larger than {MAX_IMAGE_BYTES // (1024 * 1024)}MB"

    stem = _safe_id(Path(raw_name).stem) or "image"
    digest = hashlib.sha1(data).hexdigest()[:10]
    # The digest keeps the id stable AND unique (re-uploading the same photo
    # reuses one file); the id is derived from the stored name so the scanner
    # and this return value can never disagree.
    stored = f"{stem}-{digest}{suffix}"
    image_id = _safe_id(Path(stored).stem)
    MEDIA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = MEDIA_UPLOAD_DIR / stored
    try:
        target.write_bytes(data)
    except OSError as exc:  # noqa: BLE001
        return None, f"could not store the image ({exc})"

    ok, why = validate_image(target, root=MEDIA_UPLOAD_DIR)
    if not ok:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return None, why
    entry = _entry_for(image_id, stored, "uploads", MEDIA_UPLOAD_DIR)
    if entry is None:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return None, "upload could not be read back as an image"
    registry(refresh=True)
    return entry, ""


def delete_upload(image_id: str) -> bool:
    """Delete one uploaded image (curated assets are never deletable)."""
    entry = resolve(image_id, refresh=True)
    if entry is None or entry.source != "uploads":
        return False
    try:
        entry.path.unlink(missing_ok=True)
    except OSError as exc:  # noqa: BLE001
        log.warning("could not delete %s: %s", entry.path, exc)
        return False
    registry(refresh=True)
    return True


# --------------------------------------------------------------------------- #
# delivery
# --------------------------------------------------------------------------- #
def media_base() -> str:
    return (MEDIA_PUBLIC_BASE_URL or PUBLIC_BASE_URL).rstrip("/")


def public_url(entry: MediaImage) -> str:
    return f"{media_base()}{MEDIA_URL_PATH}/{entry.rel}"


def public_base_is_reachable() -> bool:
    """Heuristic: can Meta actually fetch our media URL from the internet?

    Loopback/LAN addresses are not reachable from WhatsApp's servers, so the
    link path would fail there; the direct media upload is used instead.
    """
    base = media_base().lower()
    if not base:
        return False
    host = base.split("//", 1)[-1].split("/", 1)[0]
    if "localhost" in host or "127.0.0.1" in host or "0.0.0.0" in host:
        return False
    if host.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.")):
        return False
    if host.endswith(".local"):
        return False
    return base.startswith(("http://", "https://"))


class MediaError(RuntimeError):
    pass


# Uploaded media ids stay valid for weeks and are reusable, so a fleet carousel
# uploads each car photo once instead of on every browse tap.
_MEDIA_ID_TTL = 7 * 24 * 3600
_media_id_cache: dict[tuple[str, str], tuple[float, str]] = {}


def _cached_media_id(phone_id: str, rel: str) -> str:
    hit = _media_id_cache.get((phone_id, rel))
    if hit and hit[0] > time.time():
        return hit[1]
    return ""


def _remember_media_id(phone_id: str, rel: str, media_id: str) -> None:
    if phone_id and rel and media_id:
        _media_id_cache[(phone_id, rel)] = (time.time() + _MEDIA_ID_TTL, media_id)


async def prepare_carousel_cards(
    cards: list[Any],
    *,
    phone_id: str,
    upload: Callable[[Path, str], Awaitable[str]],
) -> list[dict[str, Any]]:
    """Turn Outgoing carousel cards into Cloud-API card payloads.

    Local dev servers are not reachable by Meta, so registry images are uploaded
    once (id cached) and referenced by media id; when the media base URL is
    public the cheaper link form is used. Uploads run concurrently (max 5).
    """
    sem = asyncio.Semaphore(5)
    prepared: list[dict[str, Any]] = []

    async def one(card: Any) -> dict[str, Any] | None:
        entry = resolve(str(getattr(card, "image_id", "") or "")) if getattr(card, "image_id", "") else None
        header: dict[str, Any] | None = None
        if entry is not None:
            if public_base_is_reachable() or not MEDIA_DIRECT_UPLOAD:
                header = {"type": "image", "image": {"link": public_url(entry)}}
            else:
                media_id = _cached_media_id(phone_id, entry.rel)
                if not media_id:
                    async with sem:
                        media_id = await upload(entry.path, entry.mime)
                    _remember_media_id(phone_id, entry.rel, media_id)
                header = {"type": "image", "image": {"id": media_id}}
        else:
            url = str(getattr(card, "image_url", "") or "").strip()
            if url.lower().startswith(("http://", "https://")):
                header = {"type": "image", "image": {"link": url}}
        if header is None:
            log.warning("carousel card skipped: no sendable image (%r)", card)
            return None
        return {
            "header": header,
            "body_text": str(getattr(card, "body_text", "") or ""),
            "buttons": list(getattr(card, "buttons", []) or []),
        }

    tasks = [one(card) for card in cards]
    for item in await asyncio.gather(*tasks):
        if item is not None:
            prepared.append(item)
    return prepared


async def send_image(image_id: str, recipient: str, caption: str | None = None) -> dict:
    """Reusable media sender: registry id → actual WhatsApp image message.

    The ONE place images are delivered from, so the agent turn and the owner
    console cannot drift apart. Prefers a direct media upload (works with a
    local dev server); falls back to the public link when the base URL is
    internet-reachable or the upload is refused.
    """
    entry = resolve(image_id)
    if entry is None:
        raise MediaError(f"unknown image id {image_id!r}")
    ok, why = validate_image(entry.path)
    if not ok:
        raise MediaError(f"image {entry.id!r} not sendable: {why}")

    from app.kapso import kapso

    cap = (caption or "").strip()[:1024]
    if MEDIA_DIRECT_UPLOAD and not public_base_is_reachable():
        try:
            media_id = await kapso.upload_media(entry.path, entry.mime)
            sent = await kapso.send_image_by_id(recipient, media_id, cap)
            sent["media_id"] = media_id
            sent["via"] = "upload"
            return sent
        except Exception as exc:  # noqa: BLE001
            log.warning("direct media upload failed (%s) — trying the public link", exc)
    url = public_url(entry)
    sent = await kapso.send_image(recipient, url, cap)
    sent["url"] = url
    sent["via"] = "link"
    return sent
