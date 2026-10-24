"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { say } from "@/components/flash";

interface Channel {
  id: string;
  name: string;
  provider: string;
  phone_number: string;
  status: string;
  enabled: boolean;
  is_primary: boolean;
  last_error: string;
  last_checked_at: string | null;
  credentials_set: string[];
  webhook_url: string;
}

interface ProviderMeta {
  id: string;
  label: string;
  fields: string[];
}

interface ConnectionInfo {
  provider: string;
  credential_state: string;
  credentials: {
    api_key_set: boolean;
    phone_number_id_set: boolean;
    webhook_secret_set: boolean;
  };
  verified: boolean;
  connected: boolean;
  detail: string;
  error: string;
  webhook_url: string;
  note: string;
  phone_number?: {
    display_phone_number: string;
    verified_name: string;
    quality_rating: string;
    status: string;
  };
}

const FIELD_LABELS: Record<string, string> = {
  api_key: "API key",
  phone_number_id: "Phone number ID",
  webhook_secret: "Webhook secret (HMAC)",
  access_token: "Access token",
  verify_token: "Verify token",
  send_url: "Send endpoint URL (POST {to, text})",
  send_bearer_token: "Bearer token (optional)",
  secret_header: "Secret header value (optional)",
  account_sid: "Account SID",
  auth_token: "Auth token",
};

const STATUS_DOT: Record<string, string> = {
  connected: "bg-[#2fbf71]",
  connecting: "bg-[#c9a961]",
  error: "bg-[#e05555]",
  disconnected: "bg-[#6b727d]",
};

export default function ConnectionPanel() {
  /* env Kapso state */
  const [state, setState] = useState<ConnectionInfo | null>(null);
  const [checking, setChecking] = useState(true);

  /* channels */
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [providers, setProviders] = useState<ProviderMeta[]>([]);
  const [showWizard, setShowWizard] = useState(false);
  const [wProvider, setWProvider] = useState("kapso");
  const [wName, setWName] = useState("");
  const [wPhone, setWPhone] = useState("");
  const [wPrimary, setWPrimary] = useState(false);
  const [wCreds, setWCreds] = useState<Record<string, string>>({});
  const [wBusy, setWBusy] = useState(false);

  const [testing, setTesting] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const check = useCallback(() => {
    setChecking(true);
    api<ConnectionInfo>("/api/connection")
      .then(setState)
      .catch(() => setState(null))
      .finally(() => setChecking(false));
  }, []);

  const loadChannels = useCallback(() => {
    api<{ channels: Channel[] }>("/api/channels")
      .then((d) => setChannels(d.channels))
      .catch(() => {});
    api<{ providers: ProviderMeta[] }>("/api/channels/meta")
      .then((d) => setProviders(d.providers))
      .catch(() => {});
  }, []);

  useEffect(() => {
    check();
    loadChannels();
  }, [check, loadChannels]);

  const create = async () => {
    setWBusy(true);
    try {
      const d = await api<{ channel: Channel }>("/api/channels", {
        method: "POST",
        body: JSON.stringify({
          name: wName || providers.find((p) => p.id === wProvider)?.label || wProvider,
          provider: wProvider,
          phone_number: wPhone,
          primary: wPrimary,
          credentials: wCreds,
        }),
      });
      say(true, `“${d.channel.name}” added${d.channel.is_primary ? " as the primary command center" : ""}. Run Test to validate the credentials.`);
      setShowWizard(false);
      setWName(""); setWPhone(""); setWCreds({}); setWPrimary(false);
      loadChannels();
    } catch (e) {
      say(false, `Add failed: ${(e as Error).message}`);
    } finally {
      setWBusy(false);
    }
  };

  const testChannel = async (id: string) => {
    setTesting(id);
    try {
      const d = await api<{ ok: boolean; detail?: string; error?: string }>(
        `/api/channels/${id}/test`, { method: "POST" }
      );
      say(d.ok, d.ok ? `Test OK — ${d.detail}` : `Test failed — ${d.error}`);
      loadChannels();
    } catch (e) {
      say(false, `Test failed: ${(e as Error).message}`);
    } finally {
      setTesting(null);
    }
  };

  const makePrimary = async (id: string) => {
    try {
      await api(`/api/channels/${id}/primary`, { method: "POST" });
      say(true, "Primary command center switched — replies now route through this channel.");
      loadChannels();
    } catch (e) {
      say(false, (e as Error).message);
    }
  };

  const toggleEnabled = async (ch: Channel) => {
    try {
      await api(`/api/channels/${ch.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !ch.enabled }),
      });
      say(true, ch.enabled ? `“${ch.name}” disconnected.` : `“${ch.name}” connected.`);
      loadChannels();
    } catch (e) {
      say(false, (e as Error).message);
    }
  };

  const remove = async (ch: Channel) => {
    if (!window.confirm(`Delete “${ch.name}”? Credentials are removed with it.`)) return;
    try {
      await api(`/api/channels/${ch.id}`, { method: "DELETE" });
      say(true, `“${ch.name}” deleted.`);
      loadChannels();
    } catch (e) {
      say(false, (e as Error).message);
    }
  };

  const copyWebhook = (ch: Channel) => {
    const url = `${window.location.protocol}//${window.location.hostname}:8022${ch.webhook_url}`;
    navigator.clipboard?.writeText(url).catch(() => {});
    setCopied(ch.id);
    setTimeout(() => setCopied(null), 1500);
  };

  const wizard = providers.find((p) => p.id === wProvider);

  return (
    <div className="space-y-6">
      {/* env Kapso connection */}
      <div className="rounded-2xl border border-white/10 bg-[var(--ink-2)] p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-[16px] font-medium">Default Kapso connection (.env)</h3>
            <p className="mt-1 text-[13px] text-[var(--muted)]">
              The transport configured in <code className="mono text-[11.5px] text-brass">backend/.env</code> —
              verified live against the Kapso platform API.
            </p>
          </div>
          <button onClick={check} className="btn-ghost rounded-full px-4 py-2 text-[12.5px]">
            {checking ? "Checking…" : "↻ Re-check"}
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className={`mono inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] ${
            state?.connected ? "border-[var(--green)]/40 bg-[var(--green)]/10 text-[var(--green)]" : "border-red-500/40 bg-red-500/10 text-red-300"
          }`}>
            <span className={`h-2 w-2 rounded-full ${state?.connected ? "bg-[#2fbf71]" : "bg-[#e05555]"}`} />
            {state?.connected ? "CONNECTED" : checking ? "CHECKING…" : "DISCONNECTED"}
          </span>
          {state?.phone_number && (
            <span className="mono rounded-full border border-white/10 bg-[var(--ink)] px-3 py-1.5 text-[11px] text-[#e9edef]">
              {state.phone_number.verified_name} · {state.phone_number.display_phone_number}
              {state.phone_number.quality_rating ? ` · quality ${state.phone_number.quality_rating}` : ""}
            </span>
          )}
          {state?.detail && !state.phone_number && (
            <span className="mono rounded-full border border-white/10 bg-[var(--ink)] px-3 py-1.5 text-[11px] text-[#e9edef]">
              {state.detail}
            </span>
          )}
        </div>
        {state?.error && (
          <div className="mt-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[12.5px] text-red-300">{state.error}</div>
        )}
        {state?.webhook_url && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-white/5 bg-[#0a0c10] px-3 py-2.5">
            <span className="mono text-[10px] uppercase tracking-[0.14em] text-[var(--dim)]">Webhook</span>
            <code className="mono min-w-0 flex-1 truncate text-[11px] text-brass">{state.webhook_url}</code>
          </div>
        )}
        {state?.note && (
          <p className="mt-2 text-[12px] leading-relaxed text-[var(--dim)]">{state.note}</p>
        )}
      </div>

      {/* channels — WhatsApp-style list with + button */}
      <div className="rounded-2xl border border-white/10 bg-[var(--ink-2)] p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-[16px] font-medium">WhatsApp channels</h3>
            <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-[var(--muted)]">
              Add more numbers / APIs with the <span className="text-[var(--green)]">＋</span> button — Kapso,
              Meta Cloud API, Twilio or any generic webhook. The <span className="text-brass">primary</span>{" "}
              channel answers customers and sends replies.
            </p>
          </div>
          {/* WhatsApp-style floating + button */}
          <button
            onClick={() => setShowWizard((v) => !v)}
            aria-label="Add new WhatsApp channel"
            title="Add a new WhatsApp channel / API"
            className="grid h-11 w-11 place-items-center rounded-full bg-[#00a884] text-[24px] font-light leading-none text-white shadow-[0_8px_20px_-6px_rgba(0,168,132,.7)] transition-transform hover:scale-105 active:scale-95"
          >
            {showWizard ? "×" : "+"}
          </button>
        </div>

        {/* wizard */}
        {showWizard && (
          <div className="mt-5 rounded-2xl border border-white/10 bg-[#0a0c10] p-5">
            <div className="mono text-[11px] uppercase tracking-[0.16em] text-[var(--dim)]">
              New WhatsApp channel — no code, no restart
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="text-[12.5px]">
                <span className="mb-1.5 block text-[var(--muted)]">Provider</span>
                <select
                  value={wProvider}
                  onChange={(e) => { setWProvider(e.target.value); setWCreds({}); }}
                  className="w-full rounded-xl border border-white/10 bg-[var(--ink)] px-3.5 py-2.5 text-[13.5px] text-[var(--ivory)] outline-none focus:border-[var(--green)]"
                >
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>{p.label}</option>
                  ))}
                </select>
              </label>
              <label className="text-[12.5px]">
                <span className="mb-1.5 block text-[var(--muted)]">Display name</span>
                <input
                  value={wName}
                  onChange={(e) => setWName(e.target.value)}
                  placeholder="e.g. ZoomRideXX WhatsApp"
                  className="w-full rounded-xl border border-white/10 bg-[var(--ink)] px-3.5 py-2.5 text-[13.5px] outline-none focus:border-[var(--green)]"
                />
              </label>
              <label className="text-[12.5px]">
                <span className="mb-1.5 block text-[var(--muted)]">WhatsApp number (E.164, digits)</span>
                <input
                  value={wPhone}
                  onChange={(e) => setWPhone(e.target.value)}
                  placeholder="15551234567"
                  className="w-full rounded-xl border border-white/10 bg-[var(--ink)] px-3.5 py-2.5 text-[13.5px] outline-none focus:border-[var(--green)]"
                />
              </label>
            </div>
            {wizard && (
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {wizard.fields.map((f) => (
                  <label key={f} className="text-[12.5px]">
                    <span className="mb-1.5 block text-[var(--muted)]">{FIELD_LABELS[f] || f}</span>
                    <input
                      type={/secret|token|key/i.test(f) ? "password" : "text"}
                      value={wCreds[f] || ""}
                      onChange={(e) => setWCreds((c) => ({ ...c, [f]: e.target.value }))}
                      autoComplete="off"
                      className="w-full rounded-xl border border-white/10 bg-[var(--ink)] px-3.5 py-2.5 text-[13.5px] outline-none focus:border-[var(--green)]"
                    />
                  </label>
                ))}
              </div>
            )}
            <label className="mt-4 flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={wPrimary} onChange={(e) => setWPrimary(e.target.checked)} className="accent-[#00a884]" />
              Make this the primary command center
            </label>
            <div className="mt-5 flex gap-3">
              <button onClick={create} disabled={wBusy} className="btn-primary rounded-full px-5 py-2.5 text-[13.5px] font-semibold disabled:opacity-50">
                {wBusy ? "Adding…" : "Add channel"}
              </button>
              <button onClick={() => setShowWizard(false)} className="btn-ghost rounded-full px-5 py-2.5 text-[13.5px]">Cancel</button>
            </div>
          </div>
        )}

        {/* channel list */}
        <div className="mt-5 space-y-3">
          {channels === null && (
            <div className="mono rounded-2xl border border-white/10 bg-[var(--ink)] px-5 py-8 text-center text-[12.5px] text-[var(--dim)]">
              LOADING CHANNELS…
            </div>
          )}
          {channels?.length === 0 && (
            <div className="rounded-2xl border border-dashed border-white/15 bg-[var(--ink)] px-5 py-8 text-center">
              <div className="text-[26px]">📱</div>
              <div className="mt-2 text-[14px]">No extra channels yet — the default .env Kapso transport handles everything.</div>
              <p className="mt-1 text-[12.5px] text-[var(--muted)]">
                Tap ＋ to connect another number or provider (Meta Cloud API, Twilio, generic webhook).
              </p>
            </div>
          )}
          {channels?.map((ch) => (
            <div key={ch.id} className={`rounded-2xl border p-4 ${ch.is_primary ? "border-[var(--green)]/40 bg-[var(--green)]/[0.05]" : "border-white/10 bg-[var(--ink)]"}`}>
              <div className="flex flex-wrap items-center gap-3">
                <span className="grid h-9 w-9 place-items-center rounded-lg border border-white/10 bg-[#0a0c10] text-[16px]">
                  {ch.provider === "kapso" ? "🟢" : ch.provider === "meta" ? "🟦" : ch.provider === "twilio" ? "🟥" : "🔗"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14.5px] font-medium">{ch.name}</span>
                    {ch.is_primary && (
                      <span className="mono rounded-full bg-[var(--green)] px-2.5 py-0.5 text-[10px] font-bold text-[#06130c]">
                        PRIMARY
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-[var(--muted)]">
                    <span className="mono">{ch.provider}</span>
                    {ch.phone_number && <span className="mono">+{ch.phone_number}</span>}
                    <span className="flex items-center gap-1.5">
                      <span className={`h-2 w-2 rounded-full ${STATUS_DOT[ch.status] || STATUS_DOT.disconnected}`} />
                      {ch.status.toUpperCase()}
                    </span>
                    {ch.last_error && <span className="text-red-400">⚠ {ch.last_error.slice(0, 80)}</span>}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {!ch.is_primary && (
                    <button onClick={() => makePrimary(ch.id)} className="btn-primary rounded-full px-3.5 py-2 text-[12px] font-semibold">
                      ⭐ Make primary
                    </button>
                  )}
                  <button onClick={() => testChannel(ch.id)} disabled={testing === ch.id} className="btn-ghost rounded-full px-3.5 py-2 text-[12px]">
                    {testing === ch.id ? "Testing…" : "↻ Test"}
                  </button>
                  <button onClick={() => toggleEnabled(ch)} className="btn-ghost rounded-full px-3.5 py-2 text-[12px]">
                    {ch.enabled ? "⏸ Disconnect" : "▶ Connect"}
                  </button>
                  <button onClick={() => remove(ch)} className="rounded-full border border-red-500/30 px-3.5 py-2 text-[12px] text-red-300 transition-colors hover:bg-red-500/10">
                    🗑
                  </button>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-white/5 bg-[#0a0c10] px-3 py-2.5">
                <span className="mono text-[10px] uppercase tracking-[0.14em] text-[var(--dim)]">Webhook</span>
                <code className="mono min-w-0 flex-1 truncate text-[11px] text-brass">{ch.webhook_url}</code>
                <button onClick={() => copyWebhook(ch)} className="btn-ghost rounded-lg px-3 py-1 text-[11px]">
                  {copied === ch.id ? "✓ Copied" : "Copy"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
