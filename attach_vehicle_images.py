#!/usr/bin/env python3
"""Attach your fleet photos to the agent — run once, safe to re-run.

WHY PHOTOS NEED A HOME IN THE PROJECT
-------------------------------------
WhatsApp cannot read your file system. A message can only carry a picture as a
*public http(s) link* or by *uploading the bytes* to the WhatsApp Cloud API. So
the agent addresses every photo by a REGISTRY ID taken from a folder inside the
project — never by an absolute path like ``D:\\cars\\seltos.jpg``, which Meta can
never fetch.

    project/backend/assets/images/<name>.jpg   →   registry id: <name>

HOW THE RIGHT PHOTO IS CHOSEN
-----------------------------
The registration plate decides it. A fleet usually holds several cars of the
SAME model, so a match on the model name alone is ambiguous — and texting a
customer the wrong car is worse than sending no picture at all. Put the plate
in the file name and the row whose fleet entry mentions that plate always gets
that exact photo:

    file : kia-seltos-ap39hr1004.jpg
    row  : name "KIA Seltos", description "Black, AP39 HR 1004, 7 seats"
    → this photo every time, with nothing to configure in the console.

USAGE
-----
    python attach_vehicle_images.py            # the photos listed below
    python attach_vehicle_images.py extra.jpg  # plus any additional files

Additional files are named from their own file name, so keep the plate in it.
Files are only re-copied when their bytes actually differ, and every file is
verified by reading it back through the agent's own registry before this script
reports success — a name the agent would reject is reported as a failure, not
as a silent no-op.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Written with forward slashes: Windows accepts them, and they avoid any
# backslash-escaping ambiguity.
PHOTOS: list[tuple[str, str]] = [
    (
        "C:/Users/HP/AppData/Local/Packages/5319275A.WhatsAppDesktop_cv1g1gvanyjgm"
        "/LocalState/sessions/5FB9D7EE02FF19E7167AA52D238452EEEE508632/transfers"
        "/2026-41/WhatsApp Image 2026-10-13 at 09.14.27.jpeg",
        "kia-seltos-ap39hr1004",
    ),
    (
        "C:/Users/HP/AppData/Local/Packages/5319275A.WhatsAppDesktop_cv1g1gvanyjgm"
        "/LocalState/sessions/5FB9D7EE02FF19E7167AA52D238452EEEE508632/transfers"
        "/2026-41/WhatsApp Image 2026-10-13 at 09.14.35.jpeg",
        "maruti-maroon-ap39fh6455",
    ),
    (
        "C:/Users/HP/AppData/Local/Temp/freebuff-desktop-pastes/paste-1791888040563-11656.png",
        "sedan-silver",
    ),
    (
        "C:/Users/HP/AppData/Local/Temp/freebuff-desktop-pastes/paste-1791888069690-11656.png",
        "honda-accord-red",
    ),
    (
        "C:/Users/HP/AppData/Local/Temp/freebuff-desktop-pastes/paste-1791888095400-11656.png",
        "maruti-swift-blue",
    ),
]

# Magic bytes → canonical extension. The extension is sniffed from the bytes
# rather than trusted from the file name, because WhatsApp hands out ".jpeg"
# files and the paste buffer hands out ".png" files, and the agent's registry
# rejects a name that disagrees with the content it finds inside.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)


def sniff_extension(data: bytes) -> str:
    """Canonical extension for real image bytes ('' when not an image)."""
    for magic, extension in _MAGIC:
        if data.startswith(magic):
            return extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def slug(value: str) -> str:
    """The id rule used by the registry — kept identical on purpose."""
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:60]


def agent_media():
    """The agent's own image module, imported after sys.path is prepared."""
    from app import media  # deliberate late import

    return media


def attach(source: str, stem: str, images_dir: Path, max_bytes: int) -> tuple[bool, str]:
    """Copy one file in and prove the agent can read it back. (ok, message)."""
    src = Path(source)
    if not src.is_file():
        return False, f"MISSING   {source}"

    try:
        data = src.read_bytes()
    except OSError as exc:
        return False, f"UNREADABLE {src.name}: {exc}"

    extension = sniff_extension(data)
    if not extension:
        return False, f"NOT IMAGE {src.name} (not a PNG/JPEG/WEBP)"
    if len(data) > max_bytes:
        return False, (
            f"TOO BIG   {src.name} ({len(data) // 1024}KB > "
            f"{max_bytes // (1024 * 1024)}MB)"
        )

    image_id = slug(stem)
    target = images_dir / f"{image_id}{extension}"
    unchanged = False
    if target.is_file():
        try:
            unchanged = target.read_bytes() == data
        except OSError:
            unchanged = False   # unreadable → just overwrite it
    if not unchanged:
        try:
            images_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            return False, f"WRITE FAIL {target.name}: {exc}"

    # The only check that counts: ask the agent's own registry to find it.
    try:
        entry = agent_media().resolve(image_id, refresh=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"VERIFY FAIL {target.name}: {exc}"
    if entry is None:
        if not unchanged:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        return False, (
            f"REJECTED  {target.name} — the agent will not serve this file "
            "(content did not validate as a real image)"
        )

    verb = "verified " if unchanged else "attached "
    return True, f"{verb} {entry.filename}  id={entry.id}  ({entry.size // 1024}KB)"


def main(argv: list[str]) -> int:
    try:
        media = agent_media()
        images_dir = Path(media.ASSETS_IMAGE_DIR)
        max_bytes = media.MAX_IMAGE_BYTES
    except Exception as exc:  # noqa: BLE001
        print(f"[X] Could not load the agent's own settings: {exc}")
        print("    Run this from the project folder (next to backend/), with the")
        print("    backend virtual environment active — attach_images.bat does both.")
        return 2

    jobs = list(PHOTOS)
    for extra in argv:
        jobs.append((extra, Path(extra).stem))

    print("=" * 72)
    print(" Attaching fleet photos")
    print(f" Destination : {images_dir}")
    print("=" * 72)

    ok_count = 0
    for source, stem in jobs:
        ok, message = attach(source, stem, images_dir, max_bytes)
        print(f"  [{'ok' if ok else '!!'}] {message}")
        ok_count += int(ok)

    print("-" * 72)
    print(f" {ok_count}/{len(jobs)} photos in place and readable by the agent.")
    if ok_count != len(jobs):
        print(" Some files were skipped — see the [!!] lines above.")
        print(" WhatsApp moves its transfer files and Windows clears %TEMP%, so if a")
        print(" photo is gone, copy it somewhere permanent and pass its path:")
        print('     python attach_vehicle_images.py "C:\\Users\\HP\\Desktop\\seltos.jpg"')
    print()
    print(" Next: restart the agent (Ctrl+C, then start.bat) — it scans this folder")
    print(" on startup, so the photos go live with no console configuration.")
    print(" Check them at:  http://localhost:8022/api/media")
    return 0 if ok_count == len(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
