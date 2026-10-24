"use client";

/* Vehicle details modal: specs, full rate card, deposit rules and a real
   availability check for a chosen window (server-verified). */
import React, { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/site/icons";
import { CarImage } from "@/components/site/chrome";
import {
  getVehicle, localInputToIso, money, waBookingLink, waNumber,
  type SiteConfig, type SiteVehicle,
} from "@/lib/site";

export function VehicleModal({
  config,
  vehicle,
  onClose,
  onBook,
}: {
  config: SiteConfig | null;
  vehicle: SiteVehicle;
  onClose: () => void;
  onBook: (v: SiteVehicle) => void;
}) {
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [check, setCheck] = useState<{ available?: boolean; alternatives?: SiteVehicle[]; error?: string }>({});
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const minStart = useMemo(() => {
    const lead = (config?.min_lead_hours ?? 2) * 3600 * 1000;
    const d = new Date(Date.now() + lead);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }, [config]);

  async function checkAvailability() {
    if (!startAt || !endAt) return;
    setChecking(true);
    setCheck({});
    try {
      const res = await getVehicle(vehicle.code, localInputToIso(startAt), localInputToIso(endAt));
      setCheck({ available: res.available, alternatives: res.alternatives });
    } catch (err) {
      setCheck({ error: err instanceof Error ? err.message : "check failed" });
    } finally {
      setChecking(false);
    }
  }

  const waHref = waBookingLink({
    whatsappNumber: waNumber(config),
    vehicle,
    startIso: startAt ? localInputToIso(startAt) : undefined,
    endIso: endAt ? localInputToIso(endAt) : undefined,
  });

  const rates: { label: string; value: number | null }[] = [
    { label: "6 hours (local)", value: vehicle.price_6h },
    { label: "12 hours", value: vehicle.price_12h },
    { label: "24 hours (full day)", value: vehicle.price_24h },
  ];

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`${vehicle.name} details`}
    >
      <div className="glass-card rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto relative border border-zoomBlue-500/40">
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-10 text-slate-400 hover:text-white bg-black/50 rounded-full p-1.5"
          aria-label="Close"
        >
          <Icon name="x" className="w-5 h-5" />
        </button>

        <div className="h-56 sm:h-64 relative overflow-hidden rounded-t-xl">
          <CarImage vehicle={vehicle} className="w-full h-full" />
          <div className="absolute inset-0 bg-gradient-to-t from-zoomDark-950 via-transparent to-transparent" />
          <div className="absolute bottom-3 left-4 right-4">
            <span className="text-[10px] uppercase tracking-wider font-bold text-zoomBlue-400 bg-black/70 px-2 py-1 rounded">
              {vehicle.category || "Fleet"} • {vehicle.code}
            </span>
            <h3 className="font-heading text-2xl font-extrabold text-white mt-1.5">{vehicle.name}</h3>
          </div>
        </div>

        <div className="p-5 sm:p-6 space-y-5">
          {vehicle.description && (
            <p className="text-sm text-slate-300 leading-relaxed">{vehicle.description}</p>
          )}

          {/* spec grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            {[
              { icon: "users" as const, label: "Seats", value: vehicle.seats ? String(vehicle.seats) : "—" },
              { icon: "settings" as const, label: "Gearbox", value: vehicle.transmission || "—" },
              { icon: "fuel" as const, label: "Fuel", value: vehicle.fuel || "—" },
              { icon: "shield" as const, label: "Deposit", value: vehicle.deposit ? money(vehicle.deposit, config?.currency) : "— Refundable" },
              { icon: "gauge" as const, label: "Included", value: vehicle.mileage_limit_per_day ? `${vehicle.mileage_limit_per_day} km/day` : "Ask desk" },
              { icon: "map-pin" as const, label: "Pickup", value: vehicle.location || config?.business.store_location || "Hub" },
            ].map((s) => (
              <div key={s.label} className="bg-zoomDark-900/80 border border-slate-800 rounded-lg p-2.5">
                <div className="flex items-center gap-1.5 text-[10px] uppercase font-bold text-slate-400 tracking-wider">
                  <Icon name={s.icon} className="w-3 h-3 text-zoomBlue-400" /> {s.label}
                </div>
                <div className="text-white font-semibold mt-1 truncate">{s.value}</div>
              </div>
            ))}
          </div>

          {/* rate card */}
          <div>
            <h4 className="text-xs uppercase font-bold text-slate-400 tracking-wider mb-2">Rate card</h4>
            <div className="grid grid-cols-3 gap-2">
              {rates.map((r) => (
                <div key={r.label} className={`rounded-lg border p-3 text-center ${r.value != null ? "bg-black/50 border-slate-800" : "bg-black/30 border-slate-800/50 opacity-50"}`}>
                  <div className="text-[10px] text-slate-400 uppercase font-semibold">{r.label}</div>
                  <div className="font-heading text-lg font-extrabold text-zoomGold-400 mt-0.5">
                    {r.value != null ? money(r.value, config?.currency) : "N/A"}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-slate-500 mt-2">
              Totals are estimates settled at pickup{vehicle.deposit ? ` • refundable deposit ${money(vehicle.deposit, config?.currency)} is separate` : ""}.
              {config?.driver_fee_per_day ? ` Chauffeur: from ${money(config.driver_fee_per_day, config?.currency)}/day.` : ""}
            </p>
          </div>

          {/* availability check */}
          <div className="bg-zoomDark-900/80 border border-slate-800 rounded-lg p-3.5">
            <h4 className="text-xs uppercase font-bold text-slate-300 tracking-wider mb-2 flex items-center gap-1.5">
              <Icon name="calendar" className="w-3.5 h-3.5 text-zoomBlue-400" /> Check availability
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 text-xs">
              <div className="sm:col-span-5">
                <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Pickup</label>
                <input
                  type="datetime-local"
                  value={startAt}
                  min={minStart}
                  onChange={(e) => setStartAt(e.target.value)}
                  className="w-full bg-black/60 border border-slate-700 focus:border-zoomBlue-400 rounded px-2.5 py-2 text-white outline-none"
                />
              </div>
              <div className="sm:col-span-5">
                <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Return</label>
                <input
                  type="datetime-local"
                  value={endAt}
                  min={startAt || minStart}
                  onChange={(e) => setEndAt(e.target.value)}
                  className="w-full bg-black/60 border border-slate-700 focus:border-zoomBlue-400 rounded px-2.5 py-2 text-white outline-none"
                />
              </div>
              <div className="sm:col-span-2 flex items-end">
                <button
                  onClick={checkAvailability}
                  disabled={!startAt || !endAt || checking}
                  className="w-full py-2 bg-zoomBlue-500 disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 text-black font-bold text-xs uppercase rounded transition"
                >
                  {checking ? "…" : "Check"}
                </button>
              </div>
            </div>
            {check.available === true && (
              <p className="mt-2.5 text-xs text-emerald-400 font-semibold flex items-center gap-1.5">
                <Icon name="check-circle" className="w-4 h-4" /> Available for that window — reserve it now.
              </p>
            )}
            {check.available === false && (
              <div className="mt-2.5 text-xs">
                <p className="text-amber-400 font-semibold flex items-center gap-1.5">
                  <Icon name="info" className="w-4 h-4" /> Already booked for that window.
                </p>
                {check.alternatives && check.alternatives.length > 0 && (
                  <p className="text-slate-400 mt-1">
                    Free instead: {check.alternatives.map((a) => a.name).join(", ")}
                  </p>
                )}
              </div>
            )}
            {check.error && <p className="mt-2.5 text-xs text-red-400">{check.error}</p>}
          </div>

          {/* CTAs */}
          <div className="grid grid-cols-2 gap-2.5">
            <button
              onClick={() => onBook(vehicle)}
              className="w-full py-3 bg-gradient-to-r from-zoomBlue-500 to-cyan-400 hover:brightness-110 text-black font-extrabold text-xs uppercase tracking-wider rounded-lg transition shadow-lg shadow-zoomBlue-500/20"
            >
              Book This Car
            </button>
            <a
              href={waHref}
              target="_blank"
              rel="noreferrer"
              className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 text-black font-extrabold text-xs uppercase tracking-wider rounded-lg transition flex items-center justify-center gap-1.5"
            >
              <Icon name="message" className="w-4 h-4 fill-black text-transparent" /> Book on WhatsApp
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
