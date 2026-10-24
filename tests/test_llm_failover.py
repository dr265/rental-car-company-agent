"""Phase 8B — the reused LLM provider chain: failover, cooldowns, secret safety.

No provider is contacted: `app.llm`'s `httpx.AsyncClient` is replaced with a fake
that answers from a per-host script. Every provider object used here is a test
fixture, so the assertions describe the *engine*, not the owner's real keys.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402  (must run first)

import app.llm as llm  # noqa: E402

PROVIDERS = [
    {"name": "p1", "base_url": "https://p1.example/v1", "api_key": "k1",
     "models": {"light": "p1-light", "complex": "p1-heavy"}},
    {"name": "p2", "base_url": "https://p2.example/v1", "api_key": "k2",
     "models": {"light": "p2-light", "complex": "p2-heavy"}},
    {"name": "p3", "base_url": "https://p3.example/v1", "api_key": "",
     "models": {"light": "p3-light", "complex": "p3-heavy"}},
]


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _ok(content: str) -> _FakeResponse:
    return _FakeResponse(200, {"choices": [{"message": {"content": content}}]})


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient inside app.llm only."""

    def __init__(self, script, calls, **_kwargs) -> None:
        self._script = script
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    def _respond(self, url: str, body, headers=None):
        host = url.split("//", 1)[-1].split("/", 1)[0]
        self._calls.append({"host": host, "url": url, "body": body,
                            "headers": dict(headers or {})})
        answer = self._script.get(host)
        if callable(answer):
            return answer(url, body)
        if answer is None:
            return _FakeResponse(500, None, "no scripted answer")
        return answer

    async def post(self, url, json=None, headers=None, **_kw):
        return self._respond(url, json, headers)

    async def get(self, url, headers=None, **_kw):
        return self._respond(url, None, headers)

    async def request(self, method, url, headers=None, **_kw):
        return self._respond(url, None, headers)


class _ChainTestCase(unittest.IsolatedAsyncioTestCase):
    """Shared setup: a scripted chain and a clean cooldown/stat table."""

    def setUp(self) -> None:
        self.calls: list[dict] = []
        self._saved_providers = llm.LLM_PROVIDERS
        self._saved_cooldowns = dict(llm._cooldowns)
        self._saved_stats = {k: dict(v) for k, v in llm._stats.items()}
        llm.LLM_PROVIDERS = PROVIDERS
        llm._cooldowns.clear()
        for name in ("p1", "p2", "p3"):
            llm._stats[name] = {"ok": 0, "fail": 0, "last_error": "",
                                "last_ok_at": "", "last_latency_ms": 0}

    def tearDown(self) -> None:
        llm.LLM_PROVIDERS = self._saved_providers
        llm._cooldowns.clear()
        llm._cooldowns.update(self._saved_cooldowns)
        llm._stats.clear()
        llm._stats.update(self._saved_stats)

    def _patch_client(self, script: dict):
        calls = self.calls

        class _Client(_FakeAsyncClient):
            def __init__(self, **kwargs) -> None:
                super().__init__(script, calls, **kwargs)

        return patch.object(llm.httpx, "AsyncClient", _Client)

    @property
    def hosts(self) -> list[str]:
        return [c["host"] for c in self.calls]


class ChainConfigurationTests(unittest.TestCase):
    """8B.13/8B.14 — the rental agent uses the shared provider registry."""

    def test_providers_come_from_the_shared_config_registry(self) -> None:
        from app.config import LLM_PROVIDERS as CONFIGURED

        self.assertTrue(CONFIGURED, "no LLM provider is configured at all")
        self.assertEqual(llm.LLM_PROVIDERS, CONFIGURED,
                         "app.llm must read the shared chain, not its own copy")

    def test_every_provider_is_shaped_consistently(self) -> None:
        from app.config import LLM_PROVIDERS as CONFIGURED

        for provider in CONFIGURED:
            with self.subTest(provider=provider["name"]):
                self.assertIn("base_url", provider)
                self.assertIn("api_key", provider)
                self.assertIn("light", provider["models"])
                self.assertIn("complex", provider["models"])

    def test_chain_order_is_preserved(self) -> None:
        from app.config import LLM_PROVIDERS as CONFIGURED

        snapshot = llm.health_snapshot()
        self.assertEqual(snapshot["chain"], [p["name"] for p in CONFIGURED])

    def test_unconfigured_providers_are_reported_as_such(self) -> None:
        snapshot = llm.health_snapshot()
        for entry in snapshot["providers"]:
            with self.subTest(provider=entry["name"]):
                self.assertIsInstance(entry["configured"], bool)


class FailoverTests(_ChainTestCase):
    """8B.15 — recoverable failures move to the next provider."""

    async def test_transient_error_fails_over_to_the_next_provider(self) -> None:
        script = {
            "p1.example": _FakeResponse(500, None, '{"error":"boom"}'),
            "p2.example": _ok('{"reply":"from p2"}'),
        }
        with self._patch_client(script):
            result = await llm.chat([{"role": "user", "content": "hi"}])
        self.assertIn("from p2", result)
        self.assertEqual(self.hosts, ["p1.example", "p2.example"])

    async def test_failed_provider_is_put_on_cooldown(self) -> None:
        script = {
            "p1.example": _FakeResponse(500, None, "boom"),
            "p2.example": _ok('{"reply":"ok"}'),
        }
        with self._patch_client(script):
            await llm.chat([{"role": "user", "content": "hi"}])
        self.assertIn("p1", llm._cooldowns)
        self.assertGreater(llm._cooldowns["p1"]["until"], time.time())

    async def test_cooldown_skips_the_provider_on_the_next_call(self) -> None:
        script = {
            "p1.example": _FakeResponse(500, None, "boom"),
            "p2.example": _ok('{"reply":"ok"}'),
        }
        with self._patch_client(script):
            await llm.chat([{"role": "user", "content": "one"}])
            self.calls.clear()
            await llm.chat([{"role": "user", "content": "two"}])
        self.assertEqual(self.hosts, ["p2.example"],
                         "a cooling-down provider was retried immediately")

    async def test_http_200_with_a_provider_error_string_fails_over(self) -> None:
        # Observed live on the 'manifest' gateway: HTTP 200 whose content is an
        # error string. It must never reach a customer.
        script = {
            "p1.example": _ok("[🦚 Manifest M302] Model is not available for this agent"),
            "p2.example": _ok('{"reply":"clean answer"}'),
        }
        with self._patch_client(script):
            result = await llm.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.strip(), '{"reply":"clean answer"}')
        self.assertEqual(self.hosts, ["p1.example", "p2.example"])

    async def test_empty_completion_fails_over(self) -> None:
        script = {
            "p1.example": _ok("   "),
            "p2.example": _ok('{"reply":"second try"}'),
        }
        with self._patch_client(script):
            result = await llm.chat([{"role": "user", "content": "hi"}])
        self.assertIn("second try", result)

    async def test_all_providers_failing_raises_rather_than_inventing_a_reply(self) -> None:
        script = {
            "p1.example": _FakeResponse(500, None, "a"),
            "p2.example": _FakeResponse(500, None, "b"),
        }
        with self._patch_client(script):
            with self.assertRaises(RuntimeError) as ctx:
                await llm.chat([{"role": "user", "content": "hi"}])
        self.assertIn("All LLM providers failed", str(ctx.exception))


class ErrorClassTests(_ChainTestCase):
    """8B.16/8B.17 — permanent failures back off hard, transient ones briefly."""

    async def test_auth_failure_backs_off_for_a_long_stretch(self) -> None:
        script = {"p1.example": _FakeResponse(401, None, "invalid api key")}
        with self._patch_client(script):
            with self.assertRaises(RuntimeError):
                await llm.chat([{"role": "user", "content": "hi"}])
        delta = llm._cooldowns["p1"]["until"] - time.time()
        self.assertGreater(delta, 25 * 60,
                           "a dead key must not be retried every couple of minutes")

    async def test_insufficient_balance_backs_off_for_a_long_stretch(self) -> None:
        script = {"p1.example": _FakeResponse(402, None, "insufficient balance")}
        with self._patch_client(script):
            with self.assertRaises(RuntimeError):
                await llm.chat([{"role": "user", "content": "hi"}])
        self.assertGreater(llm._cooldowns["p1"]["until"] - time.time(), 25 * 60)

    async def test_rate_limit_uses_a_short_cooldown(self) -> None:
        script = {"p1.example": _FakeResponse(429, None, "rate limit exceeded")}
        with self._patch_client(script):
            with self.assertRaises(RuntimeError):
                await llm.chat([{"role": "user", "content": "hi"}])
        delta = llm._cooldowns["p1"]["until"] - time.time()
        self.assertGreater(delta, 30)
        self.assertLess(delta, 90, "a 429 must not be parked for half an hour")

    async def test_rate_limit_classifier_directly(self) -> None:
        self.assertGreater(llm._cooldown_for("HTTP 429: rate limit"), 30)
        self.assertGreater(llm._cooldown_for("HTTP 401: unauthorized"), 25 * 60)
        self.assertGreater(llm._cooldown_for("HTTP 402: balance"), 25 * 60)
        self.assertGreater(llm._cooldown_for("HTTP 500: boom"), 0)

    async def test_model_error_is_reported_not_swallowed(self) -> None:
        script = {"p1.example": _FakeResponse(
            400, None, '{"error":{"message":"model p1-light does not exist"}}')}
        with self._patch_client(script):
            with self.assertRaises(RuntimeError):
                await llm.chat([{"role": "user", "content": "hi"}])
        self.assertIn("model", llm._stats["p1"]["last_error"].lower())

    async def test_invalid_model_configuration_is_detected(self) -> None:
        # 8B.17: a model id the gateway does not serve surfaces as a failure
        # with the provider's own message, not as an empty customer reply.
        script = {"p1.example": _FakeResponse(
            404, None, '{"error":{"code":"model_not_found","message":"no such model"}}'),
            "p2.example": _ok('{"reply":"fallback answered"}')}
        with self._patch_client(script):
            result = await llm.chat([{"role": "user", "content": "hi"}])
        self.assertIn("fallback answered", result)
        self.assertIn("no such model", llm._stats["p1"]["last_error"])


class SafetyTests(_ChainTestCase):
    """8B.18/8B.19 — no duplicate sends from retries, no secrets in output."""

    async def test_unsafe_base_url_is_rejected_without_any_http_call(self) -> None:
        llm.LLM_PROVIDERS = [{
            "name": "unsafe", "base_url": "http://evil.example/v1",
            "api_key": "k", "models": {"light": "m", "complex": "m"},
        }]
        with self._patch_client({}):
            with self.assertRaises(RuntimeError):
                await llm.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(self.calls, [],
                         "a plaintext remote provider URL must never be contacted")

    async def test_plaintext_loopback_is_permitted_for_local_test_servers(self) -> None:
        self.assertTrue(llm._safe_provider_url("http://localhost:1234/v1"))
        self.assertTrue(llm._safe_provider_url("https://real.example/v1"))
        self.assertFalse(llm._safe_provider_url("http://evil.example/v1"))
        self.assertFalse(llm._safe_provider_url("ftp://evil.example/v1"))

    async def test_health_snapshot_never_exposes_a_key(self) -> None:
        llm.LLM_PROVIDERS = [{
            "name": "secretive", "base_url": "https://x.example/v1",
            "api_key": "SUPER-SECRET-KEY-VALUE",
            "models": {"light": "m", "complex": "m"},
        }]
        dumped = json.dumps(llm.health_snapshot())
        self.assertNotIn("SUPER-SECRET-KEY-VALUE", dumped)

    async def test_health_snapshot_marks_a_cooling_provider(self) -> None:
        llm._cooldowns["p2"] = {"until": time.time() + 60, "error": "boom"}
        entry = next(p for p in llm.health_snapshot()["providers"] if p["name"] == "p2")
        self.assertTrue(entry["on_cooldown"])

    async def test_chat_json_retries_without_json_mode_and_parses_fences(self) -> None:
        # 8B.18: a retry happens INSIDE the provider layer; the caller sees one
        # reply object. The agent therefore cannot double-send on a retry.
        script = {
            "p1.example": _ok('```json\n{"reply": "fenced", "intent": "VEHICLE_SEARCH"}\n```'),
        }
        with self._patch_client(script):
            parsed = await llm.chat_json([{"role": "user", "content": "hi"}])
        self.assertEqual(parsed["reply"], "fenced")
        self.assertEqual(len(self.calls), 1)

    async def test_chat_json_rejects_a_non_json_reply(self) -> None:
        script = {"p1.example": _ok("I cannot help with that."),
                  "p2.example": _ok("still not json")}
        with self._patch_client(script):
            with self.assertRaises(RuntimeError):
                await llm.chat_json([{"role": "user", "content": "hi"}])

    async def test_bearer_header_is_sent_but_never_logged(self) -> None:
        script = {"p1.example": _ok('{"reply":"ok"}')}
        with self._patch_client(script):
            await llm.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(self.calls[0]["headers"].get("Authorization"), "Bearer k1")
        self.assertNotIn("k1", json.dumps(llm.health_snapshot()))
        self.assertNotIn("Bearer", json.dumps(llm.health_snapshot()))

    async def test_tier_selects_the_configured_model(self) -> None:
        script = {"p1.example": _ok('{"reply":"ok"}')}
        with self._patch_client(script):
            await llm.chat([{"role": "user", "content": "hi"}], tier="complex")
        self.assertEqual(self.calls[0]["body"]["model"], "p1-heavy")


if __name__ == "__main__":
    unittest.main()
