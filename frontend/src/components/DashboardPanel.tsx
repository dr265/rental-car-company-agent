"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Section } from "@/components/ui";

interface Stats {
  customers: number;
  conversations: number;
  handoffs_pending: number;
  messages_in: number;
  messages_out: number;
  messages_failed: number;
  documents: number;
  products: number;
  available_products: number;
  orders_total: number;
  orders_active: number;
  orders_delivered: number;
  delivered_revenue: number;
  active_order_value: number;
  vehicles: number;
  bookings_confirmed: number;
  intents: { intent: string; count: number }[];
}

interface LlmProvider {
  name: string;
  configured: boolean;
  on_cooldown: boolean;
  light_model: string;
  stats: { ok: number; fail: number; last_error: string } | null;
}

/**
 * Dashboard — live business numbers, the LLM failover chain and the intent
 * mix, all read from /api/stats and /api/llm/health.
 */
export default function DashboardPanel() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [providers, setProviders] = useState<LlmProvider[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api<Stats>("/api/stats")
      .then((d) => { setStats(d); setError(""); })
      .catch((e: Error) => setError(e.message));
    api<{ providers: LlmProvider[] }>("/api/llm/health")
      .then((d) => setProviders(d.providers || []))
      .catch(() => setProviders([]));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  const cards: [string, string | number | undefined][] = stats
    ? [
        ["Fleet size", stats.vehicles],
        ["Confirmed bookings", stats.bookings_confirmed],
        ["Customers", stats.customers],
        ["Conversations", stats.conversations],
        ["With staff", stats.handoffs_pending],
        ["Messages in", stats.messages_in],
        ["Messages out", stats.messages_out],
        ["Documents", stats.documents],
      ]
    : [];

  return (
    <div className="space-y-5">
      <Section
        title="Activity at a glance"
        subtitle="Every number is computed live from the database — no demo data, refreshed every 10 seconds."
      >
        {error && (
          <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-300">
            {error}
          </div>
        )}
        {!stats && !error && (
          <div className="mono py-4 text-center text-[12px] text-white/40">LOADING…</div>
        )}
        {stats && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {cards.map(([label, value]) => (
              <div key={label} className="tile rounded-2xl border border-white/10 bg-[var(--ink)] px-4 py-4">
                <div className="serif text-[30px] leading-none">{value ?? "—"}</div>
                <div className="mono mt-2 text-[10.5px] uppercase tracking-[0.14em] text-[var(--dim)]">{label}</div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section
          title="LLM failover chain"
          subtitle="Providers are tried in order; a failing one is skipped on a cooldown."
        >
          {providers === null && <div className="mono py-4 text-center text-[12px] text-white/40">LOADING…</div>}
          {providers && providers.length === 0 && (
            <p className="text-[13px] text-ivory/50">No provider information available.</p>
          )}
          {providers && providers.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12.5px]">
                <thead>
                  <tr className="mono border-b border-white/10 text-[10px] uppercase tracking-wider text-white/40">
                    <th className="py-2 pr-3">provider</th>
                    <th className="py-2 pr-3">state</th>
                    <th className="py-2 pr-3">ok/fail</th>
                    <th className="py-2 pr-3">last error</th>
                  </tr>
                </thead>
                <tbody>
                  {providers.map((p) => {
                    const pill = p.on_cooldown
                      ? "border-brass/40 bg-brass/10 text-brass"
                      : p.configured
                        ? "border-jewel/40 bg-jewel/10 text-jewel"
                        : "border-white/15 text-white/50";
                    const label = p.on_cooldown ? "cooldown" : p.configured ? "ready" : "no key";
                    return (
                      <tr key={p.name} className="border-b border-white/5">
                        <td className="py-2.5 pr-3">
                          <div>{p.name}</div>
                          <div className="mono text-[10px] text-white/40">{p.light_model}</div>
                        </td>
                        <td className="py-2.5 pr-3">
                          <span className={`mono rounded-full border px-2 py-0.5 text-[10px] ${pill}`}>{label}</span>
                        </td>
                        <td className="mono py-2.5 pr-3">
                          {p.stats?.ok ?? 0}/{p.stats?.fail ?? 0}
                        </td>
                        <td className="max-w-[220px] truncate py-2.5 pr-3 text-white/40" title={p.stats?.last_error || ""}>
                          {(p.stats?.last_error || "").slice(0, 80)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        <Section
          title="Intent mix (outbound)"
          subtitle="What the agent has actually been doing in customer chats."
        >
          {!stats && <div className="mono py-4 text-center text-[12px] text-white/40">LOADING…</div>}
          {stats && (stats.intents?.length ?? 0) === 0 && (
            <p className="text-[13px] text-ivory/50">No replies yet — message the business number to see intents here.</p>
          )}
          {stats && (stats.intents?.length ?? 0) > 0 && (
            <div className="space-y-2">
              {stats.intents.map((i) => {
                const total = stats.intents.reduce((s, x) => s + x.count, 0) || 1;
                const pct = Math.round((i.count / total) * 100);
                return (
                  <div key={i.intent}>
                    <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
                      <span className="mono truncate text-ivory/80">{i.intent}</span>
                      <span className="mono text-[11px] text-[var(--dim)]">
                        {i.count} · {pct}%
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
                      <div
                        className="h-full rounded-full bg-[var(--green)]"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}
