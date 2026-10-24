"use client";

/* Fleet & rates: live search, 6/12/24h duration toggle, category pills, and
   one card per listed vehicle — every price straight from the database. */
import React, { useMemo, useState } from "react";
import { Icon } from "@/components/site/icons";
import { CarImage } from "@/components/site/chrome";
import { money, waBookingLink, waNumber, type SiteConfig, type SiteVehicle } from "@/lib/site";
import type { FleetFilter } from "@/components/site/hero";

const CATEGORY_ORDER = ["SUV & 4x4", "Compact SUV", "Sedan", "Hatchback & MUV"];

export function FleetSection({
  config,
  vehicles,
  categories,
  filter,
  onFilterChange,
  loading,
  error,
  onRetry,
  onQuickBook,
  onDetails,
}: {
  config: SiteConfig | null;
  vehicles: SiteVehicle[];
  categories: string[];
  filter: FleetFilter;
  onFilterChange: (f: FleetFilter) => void;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onQuickBook: (v: SiteVehicle) => void;
  onDetails: (v: SiteVehicle) => void;
}) {
  const [search, setSearch] = useState("");

  const orderedCategories = useMemo(() => {
    const rest = categories.filter((c) => !CATEGORY_ORDER.includes(c));
    return [...CATEGORY_ORDER.filter((c) => categories.includes(c)), ...rest];
  }, [categories]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return vehicles.filter((v) => {
      const matchesCat = filter.category === "all" || v.category === filter.category;
      const matchesSearch =
        !q ||
        v.name.toLowerCase().includes(q) ||
        v.fuel.toLowerCase().includes(q) ||
        v.category.toLowerCase().includes(q) ||
        (v.description || "").toLowerCase().includes(q);
      return matchesCat && matchesSearch;
    });
  }, [vehicles, search, filter.category]);

  const countFor = (cat: string) =>
    cat === "all" ? vehicles.length : vehicles.filter((v) => v.category === cat).length;

  const priceFor = (v: SiteVehicle): { label: string; value: string } => {
    if (filter.duration === "6h") {
      return v.price_6h != null
        ? { label: "6 Hours Package", value: money(v.price_6h) }
        : { label: "6 Hours Package", value: "12h min." };
    }
    if (filter.duration === "12h") return { label: "12 Hours Package", value: money(v.price_12h) };
    return { label: "24 Hours (Full Day)", value: money(v.price_24h) };
  };

  return (
    <section id="fleet" className="py-16 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 scroll-mt-28">
      <div className="text-center max-w-3xl mx-auto mb-8">
        <span className="text-zoomBlue-400 font-heading text-xs uppercase tracking-[0.25em] font-bold">
          {vehicles.length} Verified Vehicles
        </span>
        <h2 className="font-heading text-3xl sm:text-4xl font-extrabold text-white mt-1">Our Fleet &amp; Transparent Rates</h2>
        <p className="text-slate-400 text-xs sm:text-sm mt-2">
          No hidden fees or unexpected deposit cuts. 24/7 roadside assistance included on all packages.
        </p>

        {/* live search */}
        <div className="relative max-w-md mx-auto mt-6">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search any car (e.g. Thar, Fortuner, Swift, Creta...)"
            aria-label="Search the fleet"
            className="w-full bg-zoomDark-900/90 border border-slate-700 focus:border-zoomBlue-400 rounded-full pl-10 pr-4 py-2.5 text-xs text-white placeholder-slate-500 outline-none backdrop-blur shadow-inner transition"
          />
          <Icon name="search" className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
        </div>

        {/* duration toggle */}
        <div className="inline-flex flex-wrap justify-center p-1.5 bg-zoomDark-900 border border-slate-800 rounded-lg mt-6 shadow-inner gap-1">
          {(["24h", "12h", "6h"] as const).map((d) => (
            <button
              key={d}
              onClick={() => onFilterChange({ ...filter, duration: d })}
              className={`px-4 sm:px-5 py-2.5 rounded-md text-xs font-bold uppercase tracking-wider transition ${
                filter.duration === d
                  ? "bg-zoomBlue-500 text-black shadow"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {d === "24h" ? "⭐ 24 Hours Rate (Full Day)" : d === "12h" ? "12 Hours Rate" : "6 Hours Rate"}
            </button>
          ))}
        </div>

        {/* category pills */}
        <div className="flex flex-wrap items-center justify-center gap-2 mt-5">
          {["all", ...orderedCategories].map((cat) => (
            <button
              key={cat}
              onClick={() => onFilterChange({ ...filter, category: cat })}
              className={`px-4 py-1.5 rounded-full text-xs font-semibold transition border ${
                filter.category === cat
                  ? "bg-zoomBlue-500 text-black border-zoomBlue-500 font-bold shadow"
                  : "bg-zoomDark-900 text-slate-400 border-slate-800 hover:text-white"
              }`}
            >
              {cat === "all" ? `All (${countFor("all")} Vehicles)` : `${cat} (${countFor(cat)})`}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8" aria-busy="true">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="glass-card rounded-xl overflow-hidden animate-pulse">
              <div className="h-52 bg-zoomDark-800/60" />
              <div className="p-5 space-y-3">
                <div className="h-5 bg-zoomDark-800/80 rounded w-2/3" />
                <div className="h-14 bg-zoomDark-800/50 rounded" />
                <div className="h-9 bg-zoomDark-800/40 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {error && !loading && (
        <div className="glass-card rounded-xl p-8 text-center max-w-xl mx-auto border border-red-500/30">
          <Icon name="info" className="w-8 h-8 mx-auto mb-3 text-red-400" />
          <p className="text-slate-200 text-sm font-semibold">Couldn&apos;t load the fleet</p>
          <p className="text-slate-400 text-xs mt-1">{error}</p>
          <button
            onClick={onRetry}
            className="mt-4 px-4 py-2 bg-zoomBlue-500 hover:brightness-110 text-black text-xs font-bold uppercase tracking-wider rounded transition"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="col-span-full text-center py-12 glass-card rounded-xl">
          <p className="text-slate-400 text-sm">
            No cars found matching &quot;{search}&quot;{filter.category !== "all" ? ` in ${filter.category}` : ""}.
          </p>
          <button
            onClick={() => { setSearch(""); onFilterChange({ ...filter, category: "all" }); }}
            className="mt-3 px-4 py-1.5 bg-zoomBlue-500 text-black text-xs font-bold rounded hover:brightness-110 transition"
          >
            Show All Cars
          </button>
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {filtered.map((car) => {
            const p = priceFor(car);
            const waHref = waBookingLink({
              whatsappNumber: waNumber(config),
              vehicle: car,
              hours: parseInt(filter.duration, 10),
            });
            return (
              <article
                key={car.code}
                className="glass-card rounded-xl overflow-hidden border border-slate-800 hover:border-zoomBlue-500/60 transition duration-500 group flex flex-col justify-between"
              >
                <div>
                  <button
                    onClick={() => onDetails(car)}
                    className="h-52 bg-black/60 relative overflow-hidden w-full block text-left"
                    aria-label={`View ${car.name} details`}
                  >
                    <CarImage vehicle={car} className="w-full h-full group-hover:scale-105 transition duration-700" />
                    <span className="absolute top-3 left-3 bg-black/80 text-zoomBlue-400 border border-zoomBlue-500/30 text-[10px] font-bold px-2.5 py-1 rounded uppercase tracking-wider">
                      {car.fuel || "Fleet"}
                    </span>
                    {car.seats ? (
                      <span className="absolute top-3 right-3 bg-zoomDark-900/90 text-slate-300 text-[10px] font-semibold px-2 py-1 rounded">
                        {car.seats} Seater
                      </span>
                    ) : null}
                  </button>

                  <div className="p-5">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="font-heading text-xl font-bold text-white group-hover:text-zoomBlue-400 transition">
                        <button onClick={() => onDetails(car)} className="text-left">{car.name}</button>
                      </h3>
                      <span className="text-[10px] text-slate-500 font-mono whitespace-nowrap">{car.transmission}</span>
                    </div>

                    {/* price box */}
                    <div className="mt-4 p-3 bg-black/50 rounded-lg border border-slate-800/80 flex items-baseline justify-between gap-2">
                      <div>
                        <span className="text-[10px] text-slate-400 uppercase font-semibold">{p.label}</span>
                        <div className="text-2xl font-heading font-extrabold text-zoomGold-400">{p.value}</div>
                      </div>
                      <div className="text-right text-[10px] text-slate-500 font-medium leading-4">
                        <div>6h: {car.price_6h != null ? money(car.price_6h) : "—"}</div>
                        <div>12h: {car.price_12h != null ? money(car.price_12h) : "—"}</div>
                        <div>24h: {car.price_24h != null ? money(car.price_24h) : "—"}</div>
                      </div>
                    </div>

                    <div className="mt-3 flex items-center gap-3 text-[11px] text-slate-400">
                      <span className="flex items-center gap-1"><Icon name="check" className="w-3.5 h-3.5 text-emerald-400" /> Sanitized</span>
                      <span className="flex items-center gap-1"><Icon name="check" className="w-3.5 h-3.5 text-emerald-400" /> AC</span>
                      <span className="flex items-center gap-1"><Icon name="check" className="w-3.5 h-3.5 text-emerald-400" /> 24×7 Assistance</span>
                    </div>
                  </div>
                </div>

                <div className="p-5 pt-0 grid grid-cols-2 gap-2 mt-4">
                  <button
                    onClick={() => onQuickBook(car)}
                    className="w-full py-2.5 bg-zoomDark-800 hover:bg-slate-700 text-white font-bold text-xs uppercase tracking-wider rounded transition border border-slate-700"
                  >
                    Quick Book
                  </button>
                  <a
                    href={waHref}
                    target="_blank"
                    rel="noreferrer"
                    className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-black font-bold text-xs uppercase tracking-wider rounded transition flex items-center justify-center gap-1.5 shadow"
                  >
                    <Icon name="message" className="w-3.5 h-3.5 fill-black text-transparent" /> WhatsApp
                  </a>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
