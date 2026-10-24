"use client";

/* Hero: headline, quick search (duration + category → fleet), and the
   interactive spotlight card. Prices come straight from the live fleet API. */
import React, { useMemo, useState } from "react";
import { Icon } from "@/components/site/icons";
import { CarImage } from "@/components/site/chrome";
import { money, waBookingLink, waNumber, type SiteConfig, type SiteVehicle } from "@/lib/site";

export interface FleetFilter {
  duration: "6h" | "12h" | "24h";
  category: string; // "all" | category name
}

const CATEGORIES = ["all", "SUV & 4x4", "Compact SUV", "Sedan", "Hatchback & MUV"];

function heroPrice(v: SiteVehicle, duration: FleetFilter["duration"]): { label: string; value: string } {
  if (duration === "6h") {
    return v.price_6h != null
      ? { label: "6 Hours Package", value: money(v.price_6h) }
      : { label: "6 Hours Package", value: "12h min." };
  }
  if (duration === "12h") return { label: "12 Hours Package", value: money(v.price_12h) };
  return { label: "24 Hours (Full Day)", value: money(v.price_24h) };
}

export function Hero({
  config,
  vehicles,
  filter,
  onFilterChange,
  onQuickBook,
  onDetails,
}: {
  config: SiteConfig | null;
  vehicles: SiteVehicle[];
  filter: FleetFilter;
  onFilterChange: (f: FleetFilter) => void;
  onQuickBook: (v: SiteVehicle) => void;
  onDetails: (v: SiteVehicle) => void;
}) {
  const [spotlightCode, setSpotlightCode] = useState<string>("");

  const spotlight = useMemo<SiteVehicle | null>(() => {
    if (!vehicles.length) return null;
    const preferred =
      vehicles.find((v) => v.code === (spotlightCode || "ZR-THAR-ROXX")) ||
      vehicles.find((v) => v.code === "ZR-THAR-ROXX") ||
      vehicles.find((v) => (v.price_24h || 0) > 0) ||
      vehicles[0];
    return preferred;
  }, [vehicles, spotlightCode]);

  const quickPicks = useMemo(
    () =>
      ["ZR-THAR-ROXX", "ZR-FORTUNER", "ZR-SCORPIO-N", "ZR-SWIFT"]
        .map((code) => vehicles.find((v) => v.code === code))
        .filter((v): v is SiteVehicle => Boolean(v)),
    [vehicles]
  );

  const price = spotlight ? heroPrice(spotlight, filter.duration) : null;
  const waHref = spotlight
    ? waBookingLink({
        whatsappNumber: waNumber(config),
        vehicle: spotlight,
        hours: parseInt(filter.duration, 10),
      })
    : "#";

  return (
    <section id="top" className="relative min-h-[72vh] flex items-center justify-center overflow-hidden py-12 lg:py-16">
      {/* ambient light + grid */}
      <div className="absolute inset-0 z-0 pointer-events-none" aria-hidden="true">
        <div className="absolute top-1/4 left-1/4 w-[500px] h-[500px] bg-zoomBlue-500/10 rounded-full blur-[140px]" />
        <div className="absolute top-1/3 right-1/4 w-[450px] h-[450px] bg-zoomGold-500/10 rounded-full blur-[140px]" />
        <div className="absolute inset-0 dot-grid opacity-40" />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 w-full">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-center">
          {/* left column */}
          <div className="lg:col-span-7 text-left">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-zoomGold-500/30 bg-zoomGold-500/10 text-zoomGold-400 text-xs font-semibold tracking-wide mb-5">
              <Icon name="shield" className="w-3.5 h-3.5 text-emerald-400" />
              <span>100% Sanitized Fleet • Self-Drive &amp; Chauffeur</span>
            </div>

            <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl font-extrabold text-white tracking-tight leading-[1.08] mb-4">
              Rent Premium.<br />
              <span className="neon-text">Drive In Minutes.</span>
            </h1>

            <p className="text-slate-300 text-sm sm:text-base max-w-lg mb-8 leading-relaxed">
              Sanitized certified vehicles starting from just <strong className="text-zoomGold-400">₹1,000/-</strong>.
              Fast WhatsApp verification, clean interiors, and instant doorstep delivery.
            </p>

            {/* quick search */}
            <div className="glass-card p-3 rounded-2xl border border-zoomBlue-500/25 shadow-2xl max-w-xl">
              <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 text-xs">
                <div className="sm:col-span-4 bg-zoomDark-900/90 rounded-xl p-2.5 border border-slate-800">
                  <label htmlFor="heroDuration" className="block text-[10px] uppercase font-bold text-slate-400 tracking-wider">Duration</label>
                  <select
                    id="heroDuration"
                    value={filter.duration}
                    onChange={(e) => onFilterChange({ ...filter, duration: e.target.value as FleetFilter["duration"] })}
                    className="w-full bg-transparent text-white font-semibold outline-none mt-1 cursor-pointer text-xs"
                  >
                    <option value="24h">24 Hours (Full Day)</option>
                    <option value="12h">12 Hours</option>
                    <option value="6h">6 Hours (Local)</option>
                  </select>
                </div>
                <div className="sm:col-span-4 bg-zoomDark-900/90 rounded-xl p-2.5 border border-slate-800">
                  <label htmlFor="heroCategory" className="block text-[10px] uppercase font-bold text-slate-400 tracking-wider">Vehicle Type</label>
                  <select
                    id="heroCategory"
                    value={filter.category}
                    onChange={(e) => onFilterChange({ ...filter, category: e.target.value })}
                    className="w-full bg-transparent text-white font-semibold outline-none mt-1 cursor-pointer text-xs"
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c === "all"
                          ? `All Fleet (${vehicles.length} Cars)`
                          : c}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="sm:col-span-4 flex items-stretch">
                  <a
                    href="#fleet"
                    className="w-full bg-gradient-to-r from-zoomBlue-500 to-cyan-400 hover:brightness-110 text-black font-extrabold uppercase tracking-wider text-xs rounded-xl shadow-lg shadow-zoomBlue-500/25 flex items-center justify-center gap-1.5 transition py-3 sm:py-0"
                  >
                    <span>Explore Fleet</span>
                    <Icon name="arrow-right" className="w-3.5 h-3.5" />
                  </a>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-y-2 gap-x-5 mt-6 text-xs text-slate-400">
              <span className="flex items-center gap-1.5"><Icon name="check-circle" className="w-4 h-4 text-emerald-400" /> No Hidden Charges</span>
              <span className="flex items-center gap-1.5"><Icon name="check-circle" className="w-4 h-4 text-emerald-400" /> 30-Min Doorstep Delivery</span>
              <span className="flex items-center gap-1.5"><Icon name="check-circle" className="w-4 h-4 text-emerald-400" /> Fast WhatsApp KYC</span>
            </div>
          </div>

          {/* right column — spotlight card */}
          <div className="lg:col-span-5">
            {spotlight ? (
              <div className="glass-card rounded-2xl overflow-hidden border border-zoomBlue-500/30 shadow-2xl relative gold-glow">
                <div className="h-60 sm:h-72 bg-gradient-to-b from-slate-900 to-black relative overflow-hidden">
                  <CarImage vehicle={spotlight} className="w-full h-full transition-opacity duration-300" />
                  <div className="absolute inset-0 bg-gradient-to-t from-zoomDark-950 via-transparent to-black/30 pointer-events-none" />

                  <div className="absolute top-3.5 left-3.5">
                    <span className="text-[10px] uppercase tracking-wider font-extrabold px-2.5 py-1 rounded border border-zoomGold-500/40 text-zoomGold-400 bg-zoomGold-500/10 backdrop-blur-md">
                      🔥 {spotlight.category || "Popular"} pick
                    </span>
                  </div>

                  <div className="absolute bottom-3.5 left-3.5 right-3.5 flex items-end justify-between backdrop-blur-md bg-black/60 p-3 rounded-xl border border-white/10">
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Starting Rate</div>
                      <div className="flex items-baseline gap-2">
                        <span className="text-xl font-heading font-extrabold text-white">
                          {money(spotlight.price_12h ?? spotlight.price_24h)}
                        </span>
                        <span className="text-[10px] text-slate-400">/ {spotlight.price_12h ? "12h" : "24h"}</span>
                        {spotlight.price_12h && spotlight.price_24h && (
                          <>
                            <span className="text-slate-600">|</span>
                            <span className="text-xl font-heading font-extrabold text-zoomGold-400">{money(spotlight.price_24h)}</span>
                            <span className="text-[10px] text-slate-400">/ 24h</span>
                          </>
                        )}
                      </div>
                    </div>
                    <span className="text-[10px] text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">Available</span>
                  </div>
                </div>

                <div className="p-5">
                  <h3 className="font-heading text-xl font-bold text-white">{spotlight.name}</h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {spotlight.seats ? `${spotlight.seats} Seater` : ""} {spotlight.transmission ? `• ${spotlight.transmission}` : ""} {spotlight.fuel ? `• ${spotlight.fuel}` : ""}
                  </p>

                  <div className="mt-2.5 text-[11px] text-slate-300 bg-black/40 px-3 py-1.5 rounded-lg border border-slate-800 font-medium line-clamp-2">
                    {price?.label}: <span className="text-zoomGold-400 font-bold">{price?.value}</span>
                    {spotlight.deposit ? <span className="text-slate-400"> • Refundable deposit {money(spotlight.deposit)}</span> : null}
                  </div>

                  <div className="grid grid-cols-2 gap-2.5 mt-4">
                    <button
                      onClick={() => onQuickBook(spotlight)}
                      className="w-full py-2.5 bg-zoomDark-800 hover:bg-slate-700 text-white font-bold text-xs uppercase tracking-wider rounded-lg transition border border-slate-700"
                    >
                      Quick Reserve
                    </button>
                    <a
                      href={waHref}
                      target="_blank"
                      rel="noreferrer"
                      className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-black font-extrabold text-xs uppercase tracking-wider rounded-lg transition flex items-center justify-center gap-1.5 shadow"
                    >
                      <Icon name="message" className="w-3.5 h-3.5 fill-black text-transparent" /> WhatsApp
                    </a>
                  </div>

                  <div className="mt-4 pt-3.5 border-t border-slate-800">
                    <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider mb-2">Tap to inspect popular models:</div>
                    <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
                      {quickPicks.map((v) => {
                        const active = v.code === spotlight.code;
                        return (
                          <button
                            key={v.code}
                            onClick={() => setSpotlightCode(v.code)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold whitespace-nowrap transition ${
                              active
                                ? "bg-zoomBlue-500 text-black shadow"
                                : "bg-zoomDark-900 border border-slate-800 text-slate-400 hover:text-white"
                            }`}
                          >
                            {v.name.replace("Mahindra ", "").replace("Maruti Suzuki ", "").replace("Toyota ", "").replace("Hyundai ", "")}
                          </button>
                        );
                      })}
                    </div>
                    <button
                      onClick={() => onDetails(spotlight)}
                      className="mt-3 text-[11px] text-zoomBlue-400 hover:text-white font-semibold transition"
                    >
                      View full details →
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="glass-card rounded-2xl p-8 text-center text-slate-400 text-sm">
                <Icon name="car" className="w-10 h-10 mx-auto mb-3 text-zoomBlue-400/50" />
                Fleet is loading…
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
