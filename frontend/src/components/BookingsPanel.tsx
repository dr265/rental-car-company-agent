"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { EmptyState, GhostButton, Section } from "@/components/ui";
import { say } from "@/components/flash";

interface Booking {
  id: string;
  reference: string;
  status: string;
  customer: string;
  customer_phone: string;
  vehicle: string;
  vehicle_code: string;
  start_at: string | null;
  end_at: string | null;
  days: number | null;
  with_driver: boolean;
  total_estimate: number | null;
  deposit: number | null;
  currency: string;
  pickup_location: string;
  summary: string;
  created_at: string | null;
}

const STATUS_STYLE: Record<string, string> = {
  confirmed: "border-jewel/40 bg-jewel/10 text-jewel",
  cancelled: "border-red-500/40 bg-red-500/10 text-red-300",
};

function fmtDT(iso: string | null) {
  return iso ? new Date(iso).toLocaleString() : "—";
}

/**
 * Bookings — the owner's reservation view (rental-only feature). Cancel is the
 * staff-side cancel endpoint, which works even after the rental started.
 */
export default function BookingsPanel() {
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(() => {
    api<{ bookings: Booking[] }>(`/api/bookings${filter ? `?status=${filter}` : ""}`)
      .then((d) => setBookings(d.bookings))
      .catch((e: Error) => say(false, `Cannot load bookings: ${e.message}`));
  }, [filter]);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  const cancel = async (b: Booking) => {
    if (!window.confirm(`Staff-cancel booking ${b.reference || b.id}? This is recorded with an audit note.`)) return;
    try {
      const r = await api<{ status: string; reason?: string }>(
        `/api/bookings/${b.id}/cancel`,
        { method: "POST" }
      );
      if (r.status === "cancelled") {
        say(true, `Booking ${b.reference || b.id} cancelled.`);
      } else {
        say(false, `Not cancelled: ${r.reason || "unknown reason"}`);
      }
      load();
    } catch (e) {
      say(false, `Cancel failed: ${(e as Error).message}`);
    }
  };

  const filters: [string, string][] = [
    ["", "all"],
    ["confirmed", "confirmed"],
    ["pending", "pending"],
    ["cancelled", "cancelled"],
  ];

  return (
    <Section
      title="Reservations"
      subtitle="Every booking the agent has made or the team confirmed — live from the database. The agent never double-books: overlap checks run before any confirmation."
      right={
        <div className="flex flex-wrap gap-1.5">
          {filters.map(([value, label]) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`rounded-full border px-3 py-1 text-[11.5px] transition-colors ${
                filter === value
                  ? "border-[var(--green)]/50 bg-[var(--green)]/15 text-[var(--green)]"
                  : "border-white/10 text-[var(--muted)] hover:border-white/25 hover:text-[var(--ivory)]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      }
    >
      {bookings === null && <div className="mono py-4 text-center text-[12px] text-white/40">LOADING…</div>}
      {bookings?.length === 0 && (
        <EmptyState
          icon="📅"
          title={filter ? `No ${filter} bookings.` : "No reservations yet."}
          hint="Bookings appear here as soon as the agent confirms one in a WhatsApp chat (or you cancel one from this list)."
        />
      )}
      {bookings && bookings.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12.5px]">
            <thead>
              <tr className="mono border-b border-white/10 text-[10px] uppercase tracking-wider text-white/40">
                <th className="py-2 pr-3">Ref</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Customer</th>
                <th className="py-2 pr-3">Vehicle</th>
                <th className="py-2 pr-3">Window</th>
                <th className="py-2 pr-3">Estimate</th>
                <th className="py-2 pr-3"></th>
              </tr>
            </thead>
            <tbody>
              {bookings.map((b) => (
                <tr key={b.id} className="border-b border-white/5">
                  <td className="mono py-2.5 pr-3 text-brass">{b.reference || "(draft)"}</td>
                  <td className="py-2.5 pr-3">
                    <span className={`mono rounded-full border px-2 py-0.5 text-[10px] ${STATUS_STYLE[b.status] || "border-white/15 text-white/50"}`}>
                      {b.status}
                    </span>
                  </td>
                  <td className="py-2.5 pr-3">
                    <div>{b.customer || "—"}</div>
                    <div className="mono text-[10px] text-white/40">{b.customer_phone}</div>
                  </td>
                  <td className="py-2.5 pr-3">
                    <div>{b.vehicle || b.vehicle_code || "—"}</div>
                    {b.with_driver && (
                      <div className="mono text-[10px] text-[var(--brass)]">chauffeur</div>
                    )}
                    {b.pickup_location && (
                      <div className="mono text-[10px] text-white/40">from {b.pickup_location}</div>
                    )}
                  </td>
                  <td className="py-2.5 pr-3">
                    <div>{fmtDT(b.start_at)}</div>
                    <div className="mono text-[10px] text-white/40">
                      → {fmtDT(b.end_at)}{b.days ? ` · ${b.days}d` : ""}
                    </div>
                  </td>
                  <td className="py-2.5 pr-3">
                    <div>
                      {b.currency}
                      {Number(b.total_estimate ?? 0).toLocaleString("en-IN")}
                    </div>
                    <div className="mono text-[10px] text-white/40">
                      dep. {b.currency}
                      {Number(b.deposit ?? 0).toLocaleString("en-IN")}
                    </div>
                  </td>
                  <td className="py-2.5">
                    <div className="flex justify-end">
                      {b.status === "confirmed" && (
                        <GhostButton
                          onClick={() => cancel(b)}
                          className="!px-2.5 !py-1 hover:border-red-400/40 hover:text-red-300"
                        >
                          Cancel
                        </GhostButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
