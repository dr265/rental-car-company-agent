"""Phase 8G — fleet photo resolution (plate binding, promo gating, ids).

The agent may only ever send a picture it can resolve to a file inside its own
image roots, and it must send the RIGHT car's picture. A rental fleet holds
several cars of the same model, so "match the photo by model name" is not good
enough once there are two Seltos — the registration plate is what disambiguates.

These tests pin the resolution order in `app.media.resolve_vehicle_image`, which
the agent turn, `vehicles.image_for_query` and the owner console all share, so
none of them can drift apart.

Everything runs against a throwaway image folder containing tiny in-memory
PNGs/JPEGs/WEBPs: no network call, no real image directory, no customer data.
"""
from __future__ import annotations

import base64
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402  (must run first)

from app import media  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.media import (  # noqa: E402
    media_base,
    normalize_plate,
    plate_of,
    public_url,
    resolve_plate,
    resolve_vehicle_image,
)
from app.vehicles import image_for_query, upsert_vehicle  # noqa: E402

# A real 1x1 PNG. The pixels are irrelevant — what matters is that the bytes
# carry a genuine PNG signature, which is exactly what the registry validates.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYA"
    "AjCB0C8AAAAASUVORK5CYII="
)
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64                       # JPEG SOI marker
_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32   # RIFF....WEBP


class ImageRegistryTestCase(unittest.TestCase):
    """Pins the image roots to throwaway folders for the duration of one test."""

    def setUp(self) -> None:
        self._assets = Path(tempfile.mkdtemp(prefix="assets-images-"))
        self._uploads = Path(tempfile.mkdtemp(prefix="upload-images-"))
        self._orig = (media.ASSETS_IMAGE_DIR, media.MEDIA_UPLOAD_DIR)
        media.ASSETS_IMAGE_DIR = self._assets
        media.MEDIA_UPLOAD_DIR = self._uploads
        media.registry(refresh=True)

    def tearDown(self) -> None:
        media.ASSETS_IMAGE_DIR, media.MEDIA_UPLOAD_DIR = self._orig
        media.registry(refresh=True)

    def add(self, filename: str, data: bytes = _PNG) -> str:
        """Drop a file into the throwaway asset folder and return its id."""
        (self._assets / filename).write_bytes(data)
        media.registry(refresh=True)
        return media._safe_id(Path(filename).stem)


class PlateParsingTests(ImageRegistryTestCase):
    def test_plates_are_normalised_regardless_of_spacing(self) -> None:
        self.assertEqual(normalize_plate("AP39HR1004"), "AP39HR1004")
        self.assertEqual(normalize_plate("ap 39 hr-1004"), "AP39HR1004")
        self.assertEqual(normalize_plate("AP39hr1004"), "AP39HR1004")

    def test_ordinary_words_are_not_mistaken_for_plates(self) -> None:
        for text in ("KIA Seltos", "Maruti Swift", "", "self drive", "CAR-2", "SUV"):
            with self.subTest(text=text):
                self.assertEqual(normalize_plate(text), "")

    def test_plate_of_finds_the_plate_inside_a_description(self) -> None:
        self.assertEqual(
            plate_of("Black KIA Seltos, AP39 HR 1004, 7 seats"), "AP39HR1004"
        )
        self.assertEqual(plate_of("", "Maruti Swift", "maroon"), "")

    def test_resolve_plate_matches_the_file_that_carries_it(self) -> None:
        self.add("kia-seltos-ap39hr1004.png")
        self.add("maruti-maroon-ap39fh6455.png")
        entry = resolve_plate("ap 39 fh 6455")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "maruti-maroon-ap39fh6455")
        self.assertIsNone(resolve_plate("TN01ZZ0000"))
        self.assertIsNone(resolve_plate("not a plate"))


class ResolutionOrderTests(ImageRegistryTestCase):
    def test_a_public_link_always_wins(self) -> None:
        self.add("kia-seltos-ap39hr1004.png")
        url, image_id = resolve_vehicle_image(
            "https://cdn.example.com/car.jpg", code="CAR-1", name="KIA Seltos"
        )
        self.assertEqual(url, "https://cdn.example.com/car.jpg")
        self.assertEqual(image_id, "")

    def test_a_registry_id_in_image_url_selects_that_image(self) -> None:
        self.add("maruti-maroon-ap39fh6455.png")
        url, image_id = resolve_vehicle_image(
            "maruti-maroon-ap39fh6455", code="CAR-7", name="Maruti"
        )
        self.assertEqual((url, image_id), ("", "maruti-maroon-ap39fh6455"))

    def test_the_plate_beats_an_ambiguous_model_name(self) -> None:
        """Two Seltos in the fleet — the plate must pick the right one."""
        self.add("kia-seltos-ap39hr1004.png")
        self.add("kia-seltos-ap39fh6455.png")
        url, image_id = resolve_vehicle_image(
            "",
            code="CAR-2",
            name="KIA Seltos",
            category="SUV",
            description="Black, AP39 FH 6455, 7 seats",
        )
        self.assertEqual(url, "")
        self.assertEqual(image_id, "kia-seltos-ap39fh6455")

    def test_a_local_photo_is_found_by_model_name(self) -> None:
        self.add("tata-nexon-white.png")
        url, image_id = resolve_vehicle_image(
            "", code="CAR-3", name="Tata Nexon", category="SUV"
        )
        self.assertEqual(url, "")
        self.assertEqual(image_id, "tata-nexon-white")

    def test_a_vehicle_with_no_photo_resolves_to_nothing(self) -> None:
        self.assertEqual(resolve_vehicle_image("", code="CAR-4", name="Nothing Here"), ("", ""))

    def test_path_like_references_are_refused(self) -> None:
        for ref in ("../../etc/passwd", "C:/Windows/win.ini", "/etc/shadow", "..\\..\\x"):
            with self.subTest(ref=ref):
                self.assertEqual(resolve_vehicle_image(ref, name="Anything"), ("", ""))


class PromoImageryTests(ImageRegistryTestCase):
    """Stock shots must never be passed off as the customer's car."""

    def test_a_vague_body_type_request_does_not_surface_stock_imagery(self) -> None:
        self.add("sedan-silver.png")
        self.add("honda-accord-red.png")
        self.assertIsNone(media.resolve_request("show me a sedan").entry)
        self.assertIsNone(media.resolve_request("send an suv photo").entry)

    def test_naming_the_make_does_surface_it(self) -> None:
        self.add("honda-accord-red.png")
        resolution = media.resolve_request("do you have a honda accord")
        self.assertIsNotNone(resolution.entry)
        self.assertEqual(resolution.entry.id, "honda-accord-red")

    def test_the_category_fallback_only_uses_a_curated_fleet_photo(self) -> None:
        """With no promo ids configured, a category fallback is still allowed —
        but only to a file that exists in the curated registry."""
        self.add("honda-accord-red.png")
        self.assertEqual(
            resolve_vehicle_image("", code="CAR-9", name="Unnamed", category="Sedan"),
            ("", "honda-accord-red"),
        )

    def test_a_real_fleet_photo_is_still_matched_by_category(self) -> None:
        """The operator opts a photo out of the promo gate by giving it a plate."""
        self.add("sedan-fleet-ap01ab1234.png")
        url, image_id = resolve_vehicle_image(
            "", code="CAR-10", name="Unnamed", category="Sedan"
        )
        self.assertEqual(url, "")
        self.assertEqual(image_id, "sedan-fleet-ap01ab1234")


class RegistryValidationTests(ImageRegistryTestCase):
    def test_jpeg_and_webp_are_accepted(self) -> None:
        self.add("kia-seltos-ap39hr1004.jpg", _JPEG)
        self.add("maruti-swift-blue.webp", _WEBP)
        ok, why = media.validate_image(
            self._assets / "kia-seltos-ap39hr1004.jpg", root=self._assets
        )
        self.assertTrue(ok, why)
        self.assertIsNotNone(media.resolve("maruti-swift-blue"))

    def test_a_mislabelled_file_is_not_registered(self) -> None:
        """JPEG bytes behind a .png name would be sent broken — refuse it."""
        (self._assets / "fake-suv.png").write_bytes(_JPEG)
        media.registry(refresh=True)
        self.assertIsNone(media.resolve("fake-suv"))

    def test_a_non_image_is_not_registered(self) -> None:
        (self._assets / "not-a-car.png").write_bytes(b"this is just text")
        media.registry(refresh=True)
        self.assertIsNone(media.resolve("not-a-car"))


class AgentAndFleetIntegrationTests(ImageRegistryTestCase):
    def test_the_agent_helper_uses_the_same_resolver(self) -> None:
        """`_vehicle_image` is what the live turn actually calls."""
        from app.agent import _vehicle_image  # lazy: keeps this module importable alone
        from app.database import Vehicle

        self.add("kia-seltos-ap39hr1004.png")
        row = Vehicle(
            code="CAR-2",
            name="KIA Seltos",
            category="SUV",
            description="Black, AP39 HR 1004, 7 seats",
        )
        url, image_id = _vehicle_image(None, row)  # the db handle is unused
        self.assertEqual(url, "")
        self.assertEqual(image_id, "kia-seltos-ap39hr1004")

    def test_image_for_query_returns_a_renderable_url(self) -> None:
        self.add("kia-seltos-ap39hr1004.png")
        with SessionLocal() as db:
            upsert_vehicle(
                db,
                code="CAR-IMG",
                name="KIA Seltos",
                category="SUV",
                description="AP39 HR 1004",
                available=1,
            )
            db.commit()
            url = image_for_query(db, "seltos")
        self.assertTrue(url, "a matched fleet photo should produce a URL")
        self.assertTrue(url.startswith(media_base() + "/media/"), url)
        self.assertTrue(url.endswith("/kia-seltos-ap39hr1004.png"), url)

    def test_images_are_never_addressed_by_filesystem_path(self) -> None:
        self.add("kia-seltos-ap39hr1004.png")
        entry = media.resolve("kia-seltos-ap39hr1004")
        self.assertIsNotNone(entry)
        # The console/API view must expose an id + URL, never the local path.
        self.assertNotIn(str(entry.path), str(entry.as_dict()))
        self.assertEqual(public_url(entry), f"{media_base()}/media/assets/{entry.filename}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
