"""LLM provider layer with automatic failover.

All providers are OpenAI-compatible endpoints. The router tries the failover
chain in order; a provider that fails is put on a short cooldown. `light` calls
use fast/cheap models; `complex` calls may use stronger models.

No API keys are ever logged or returned by the health snapshot.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import (
    LLM_COOLDOWN_SECONDS,
    LLM_MAX_ATTEMPTS,
    LLM_PROVIDERS,
    LLM_TIMEOUT_SECONDS,
    LLM_TOTAL_TIMEOUT_SECONDS,
)

log = logging.getLogger("rental.llm")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

# provider_name -> {"until": epoch, "error": str}
_cooldowns: dict[str, dict[str, Any]] = {}
# rolling stats for /api/llm/health
_stats: dict[str, dict[str, Any]] = {
    p["name"]: {"ok": 0, "fail": 0, "last_error": "", "last_ok_at": "", "last_latency_ms": 0}
    for p in LLM_PROVIDERS
}


def _record(provider: str, ok: bool, error: str = "", latency_ms: int = 0) -> None:
    s = _stats.setdefault(provider, {"ok": 0, "fail": 0, "last_error": "", "last_ok_at": "", "last_latency_ms": 0})
    if ok:
        s["ok"] += 1
        s["last_ok_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        s["last_latency_ms"] = latency_ms
        s["last_error"] = ""
    else:
        s["fail"] += 1
        s["last_error"] = error[:300]


def health_snapshot() -> dict[str, Any]:
    providers = []
    for p in LLM_PROVIDERS:
        providers.append(
            {
                "name": p["name"],
                "configured": bool(p["api_key"]),
                "light_model": p["models"]["light"],
                "complex_model": p["models"]["complex"],
                "stats": _stats.get(p["name"], {}),
                "cooldown_until": _cooldowns[p["name"]]["until"] if p["name"] in _cooldowns else 0,
                "on_cooldown": p["name"] in _cooldowns and _cooldowns[p["name"]]["until"] > time.time(),
            }
        )
    return {"providers": providers, "chain": [p["name"] for p in LLM_PROVIDERS]}


def _extract_content(data: dict) -> str:
    try:
        return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    except Exception:
        return ""


# Some gateways return HTTP 200 with a human-readable error STRING as the
# completion content (observed live on manifest: "[🦚 Manifest M302] Model ... is
# not available for this agent"). Such text must never reach a customer, so it
# is treated as a provider failure and triggers the normal failover/cooldown.
_PROVIDER_ERROR_RE = re.compile(
    r'\[\s*[^\]]{0,6}manifest\s*m\d+\]'
    r"|not available for this agent"
    r"|harness has no model to route to"
    r"|use\s+GET\s+/v1/models\s+to\s+list",
    re.IGNORECASE,
)


def _content_is_provider_error(text: str) -> bool:
    return bool(text) and bool(_PROVIDER_ERROR_RE.search(text))


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of an LLM reply (handles code fences)."""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _cooldown_for(error: str) -> int:
    """Error-specific cooldown: retry a rate limit quickly, give up on a dead
    key/balance for a long stretch so customer messages never wait on it."""
    low = error.lower()
    if "429" in low or "rate limit" in low:
        return 65  # apinex allows 5 req/min — one minute is enough
    if "401" in low or "402" in low or "403" in low or "balance" in low or "credit" in low:
        return 30 * 60
    return LLM_COOLDOWN_SECONDS


def _safe_provider_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    if parsed.scheme == "https" and parsed.hostname:
        return True
    # HTTP is permitted only for explicitly local test servers, never for an
    # environment-controlled remote endpoint.
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


async def chat(
    messages: list[dict],
    tier: str = "light",
    json_mode: bool = False,
    max_tokens: int = 700,
    temperature: float = 0.4,
) -> str:
    """Run a bounded chat completion across the failover chain."""
    errors: list[str] = []
    deadline = time.monotonic() + LLM_TOTAL_TIMEOUT_SECONDS
    attempts = 0
    # One client for the whole chain: connection reuse, and a single place where
    # the connect/read timeout is enforced.
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS, connect=10.0), follow_redirects=False
    ) as client:
        for p in LLM_PROVIDERS:
            if attempts >= LLM_MAX_ATTEMPTS or time.monotonic() >= deadline:
                break
            # SSRF guard: never let an env-provided base_url point off-host or
            # downgrade to plaintext against a remote host.
            if not _safe_provider_url(p["base_url"]):
                errors.append(f"{p['name']}: unsafe base_url rejected")
                continue
            if not p["api_key"]:
                continue
            cd = _cooldowns.get(p["name"])
            if cd and cd["until"] > time.time():
                errors.append(f"{p['name']}: cooldown")
                continue
            attempts += 1
            model = p["models"].get(tier) or p["models"]["light"]
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            headers = {
                "Authorization": f"Bearer {p['api_key']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": _UA,
            }
            t0 = time.time()
            try:
                resp = await client.post(
                    p["base_url"].rstrip("/") + "/chat/completions",
                    json=body,
                    headers=headers,
                )
                latency = int((time.time() - t0) * 1000)
                if resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                content = _extract_content(data)
                if not content.strip():
                    raise RuntimeError("empty completion")
                if _content_is_provider_error(content):
                    raise RuntimeError(f"provider error in content: {content[:150]}")
                _record(p["name"], True, latency_ms=latency)
                _cooldowns.pop(p["name"], None)
                return content
            except Exception as exc:  # noqa: BLE001
                err = f"{p['name']}/{model}: {exc}"
                log.warning("LLM provider failed: %s", err)
                _record(p["name"], False, error=str(exc))
                _cooldowns[p["name"]] = {
                    "until": time.time() + _cooldown_for(str(exc)),
                    "error": str(exc)[:200],
                }
                errors.append(err)
    raise RuntimeError("All LLM providers failed: " + " | ".join(errors[:4]))


async def _proxy_chat(
    messages: list[dict], *, tier: str, json_mode: bool,
    max_tokens: int, temperature: float,
) -> str:
    """Last-resort completion through the owner's remote AI proxy.

    Only the chat payload leaves the machine — never local data, keys or the
    database. The proxy holds the real provider keys server-side; the desktop
    client authenticates with a separate AI_PROXY_TOKEN.
    """
    from app.config import AI_PROXY_TOKEN, AI_PROXY_URL

    if not AI_PROXY_URL:
        raise RuntimeError("AI_PROXY_URL not configured")
    body = {
        "tier": tier if tier in ("light", "complex") else "light",
        "json_mode": json_mode,
        "max_tokens": min(int(max_tokens), 2000),
        "temperature": temperature,
        "messages": messages,
    }
    headers = {"Content-Type": "application/json"}
    if AI_PROXY_TOKEN:
        headers["Authorization"] = f"Bearer {AI_PROXY_TOKEN}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        resp = await client.post(f"{AI_PROXY_URL}/api/v1/chat", json=body, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"proxy returned non-JSON HTTP {resp.status_code}")
    if resp.status_code >= 400 or not data.get("success"):
        err = (data.get("error") or {}) if isinstance(data.get("error"), dict) else {}
        raise RuntimeError(f"proxy error {err.get('code', resp.status_code)}: {err.get('message', '')[:150]}")
    content = str(data.get("response") or "")
    if not content.strip():
        raise RuntimeError("proxy returned empty response")
    return content


async def chat_with_proxy_fallback(
    messages: list[dict],
    tier: str = "light",
    json_mode: bool = False,
    max_tokens: int = 700,
    temperature: float = 0.4,
) -> str:
    """Direct chain first; when every key is exhausted/rate-limited, the proxy."""
    try:
        return await chat(messages, tier=tier, json_mode=json_mode,
                          max_tokens=max_tokens, temperature=temperature)
    except Exception as chain_err:  # noqa: BLE001
        from app.config import AI_PROXY_URL

        if not AI_PROXY_URL:
            raise
        log.warning("all direct providers failed (%s) — trying AI proxy", str(chain_err)[:120])
        return await _proxy_chat(messages, tier=tier, json_mode=json_mode,
                                 max_tokens=max_tokens, temperature=temperature)


async def chat_json(messages: list[dict], tier: str = "light", max_tokens: int = 700) -> dict[str, Any]:
    """Chat completion that must return a JSON object; retries once with a plain call."""
    try:
        text = await chat_with_proxy_fallback(messages, tier=tier, json_mode=True, max_tokens=max_tokens)
        obj = _extract_json(text)
        if obj is not None:
            return obj
    except Exception:
        pass
    text = await chat_with_proxy_fallback(messages, tier=tier, json_mode=False, max_tokens=max_tokens)
    obj = _extract_json(text)
    if obj is None:
        raise RuntimeError("LLM did not return valid JSON")
    return obj
