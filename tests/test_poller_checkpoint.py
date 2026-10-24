"""Poller safety: stale checkpoints must not replay week-old WhatsApp traffic."""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402  (must run first)

from app.poller import MAX_CATCHUP, clamp_checkpoint  # noqa: E402


def test_stale_checkpoint_is_clamped_to_catchup_window() -> None:
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    old = now - timedelta(days=7)

    assert clamp_checkpoint(old, now) == now - MAX_CATCHUP


def test_recent_checkpoint_is_kept() -> None:
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    recent = now - timedelta(hours=1)

    assert clamp_checkpoint(recent, now) == recent


def test_naive_checkpoint_is_treated_as_utc() -> None:
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    recent = datetime(2026, 10, 21, 11, 0)

    assert clamp_checkpoint(recent, now) == recent.replace(tzinfo=timezone.utc)
