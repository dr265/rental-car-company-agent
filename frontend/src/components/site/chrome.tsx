"use client";

/* Shared site UI pieces: nav bar, footer, car image with graceful fallback. */
import React, { useState } from "react";
import { Icon } from "@/components/site/icons";
import { mediaUrl, waNumber, type SiteConfig, type SiteVehicle } from "@/lib/site";

export function CarImage({
  vehicle,
  className = "",
  sizesHint = "(max-width: 768px) 100vw, 33vw",
}: {
  vehicle: Pick<SiteVehicle, "name" | "image_url" | "category">;
  className?: string;
  sizesHint?: string;
}) {
  const [failed, setFailed] = useState(false);
  const src = mediaUrl(vehicle.image_url);
  if (!src || failed) {
    return (
      <div
        className={`${className} bg-gradient-to-br from-zoomDark-800 via-zoomDark-900 to-black flex items-center justify-center`}
        aria-label={`${vehicle.name} photo unavailable`}
      >
        <Icon name="car" className="w-12 h-12 text-zoomBlue-400/40" />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static export, unoptimized images
    <img
      src={src}
      alt={vehicle.name}
      loading="lazy"
      onError={() => setFailed(true)}
      className={`${className} object-cover`}
    />
  );
}

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex flex-col leading-none">
      <span className="flex items-center gap-2">
        <span className="font-heading text-xl sm:text-2xl font-extrabold tracking-tight text-white uppercase">
          Zoom<span className="text-zoomGold-400">Ride</span><span className="text-zoomBlue-400">XX</span>
        </span>
        <span className="text-[9px] bg-zoomBlue-500/20 text-zoomBlue-400 border border-zoomBlue-500/40 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider">
          Rentals
        </span>
      </span>
      {!compact && (
        <span className="text-[9px] tracking-[0.18em] text-slate-400 uppercase mt-0.5">
          Driven by comfort • Trusted for cleanliness
        </span>
      )}
    </span>
  );
}

export function SiteNav({
  config,
  onOpenConcierge,
}: {
  config: SiteConfig | null;
  onOpenConcierge: () => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const waHref = `https://wa.me/${waNumber(config)}?text=${encodeURIComponent(
    "Hi ZoomRideXX, I want to inquire about car rental."
  )}`;
  const phones = config?.business.desk_phones || [];

  return (
    <>
      {/* top strip */}
      <div className="bg-black/90 border-b border-slate-800 text-xs py-2 px-4 sticky top-0 z-40 backdrop-blur-md">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4 text-slate-300">
          <div className="flex items-center space-x-2 text-[11px] sm:text-xs min-w-0">
            <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block animate-ping flex-shrink-0" />
            <span className="text-white font-medium truncate">✨ Driven by comfort, Trusted for cleanliness</span>
            <span className="text-slate-700 hidden lg:inline">•</span>
            <span className="text-slate-400 hidden lg:inline">Sanitized Self-Drive &amp; Chauffeur Fleet</span>
          </div>
          <div className="flex items-center space-x-4 ml-auto text-xs font-semibold flex-shrink-0">
            {phones.map((p, i) => (
              <span key={p} className="flex items-center gap-2">
                {i > 0 && <span className="text-slate-700 hidden sm:inline">|</span>}
                <a href={`tel:${p}`} className={i === 0 ? "text-zoomBlue-400 hover:text-white flex items-center gap-1 transition" : "text-zoomGold-400 hover:text-white flex items-center gap-1 transition"}>
                  <Icon name="phone" className="w-3.5 h-3.5" /> {p}
                </a>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* main nav */}
      <header className="glass-card border-b border-slate-800/80 sticky top-8 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 sm:h-20 flex items-center justify-between gap-3">
          <a href="#top" className="flex-shrink-0" aria-label="ZoomRideXX home">
            <BrandMark />
          </a>

          <nav className="hidden lg:flex items-center space-x-8 text-xs font-bold uppercase tracking-wider text-slate-300">
            <a href="#fleet" className="hover:text-zoomBlue-400 transition">Our Fleet &amp; Rates</a>
            <a href="#how-it-works" className="hover:text-zoomBlue-400 transition">How It Works</a>
            <a href="#support" className="hover:text-zoomBlue-400 transition">Support</a>
            <a href="/console" className="hover:text-zoomBlue-400 transition" title="Owner console">Admin</a>
          </nav>

          <div className="flex items-center space-x-2 sm:space-x-3">
            <a
              href={waHref}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-[11px] sm:text-xs uppercase tracking-wider font-bold bg-emerald-600 hover:bg-emerald-500 text-black px-3 sm:px-4 py-2.5 rounded transition shadow-lg shadow-emerald-600/20"
            >
              <Icon name="message" className="w-4 h-4 fill-black text-transparent" />
              <span className="hidden sm:inline">WhatsApp Desk</span>
              <span className="sm:hidden">WhatsApp</span>
            </a>
            <button
              onClick={onOpenConcierge}
              className="hidden sm:flex items-center gap-2 bg-zoomDark-900 border border-zoomBlue-500/40 text-zoomBlue-300 hover:text-white px-4 py-2.5 rounded font-bold text-xs uppercase tracking-wider hover:border-zoomBlue-400 transition"
            >
              <Icon name="sparkles" className="w-4 h-4 text-zoomGold-400" /> AI Concierge
            </button>
            <button
              className="lg:hidden text-slate-300 hover:text-white p-2"
              onClick={() => setMobileOpen((v) => !v)}
              aria-label="Toggle menu"
              aria-expanded={mobileOpen}
            >
              <Icon name={mobileOpen ? "x" : "menu"} className="w-5 h-5" />
            </button>
          </div>
        </div>

        {mobileOpen && (
          <nav className="lg:hidden border-t border-slate-800/80 bg-zoomDark-950/95 px-4 py-3 space-y-1 text-xs font-bold uppercase tracking-wider text-slate-300">
            <a href="#fleet" onClick={() => setMobileOpen(false)} className="block px-2 py-2.5 rounded hover:bg-zoomDark-900 hover:text-zoomBlue-400">Our Fleet &amp; Rates</a>
            <a href="#how-it-works" onClick={() => setMobileOpen(false)} className="block px-2 py-2.5 rounded hover:bg-zoomDark-900 hover:text-zoomBlue-400">How It Works</a>
            <a href="#support" onClick={() => setMobileOpen(false)} className="block px-2 py-2.5 rounded hover:bg-zoomDark-900 hover:text-zoomBlue-400">Support</a>
            <a href="/console" className="block px-2 py-2.5 rounded hover:bg-zoomDark-900 hover:text-zoomBlue-400">Admin</a>
            <button onClick={() => { setMobileOpen(false); onOpenConcierge(); }} className="w-full text-left px-2 py-2.5 rounded hover:bg-zoomDark-900 hover:text-zoomBlue-400">
              AI Concierge
            </button>
          </nav>
        )}
      </header>
    </>
  );
}

export function SiteFooter({ config }: { config: SiteConfig | null }) {
  const name = config?.business.name || "ZoomRideXX Car Rentals";
  const phones = config?.business.desk_phones || [];
  return (
    <footer id="support" className="bg-zoomDark-950 border-t border-slate-800 py-10 text-xs text-slate-500 scroll-mt-24">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div>
            <span className="font-heading text-xl font-bold text-white">
              {name.split(" ").map((w, i) =>
                i === 0
                  ? <span key={i}>Zoom<span className="text-zoomGold-400">Ride</span><span className="text-zoomBlue-400">XX</span> </span>
                  : <span key={i}>{w} </span>
              )}
            </span>
            <p className="text-[11px] text-slate-400 mt-1">
              Driven by comfort, Trusted for cleanliness • 24/7 Helpline:{" "}
              {phones.map((p, i) => (
                <span key={p}>
                  {i > 0 && " | "}
                  <a href={`tel:${p}`} className="text-slate-300 hover:text-white">{p}</a>
                </span>
              ))}
            </p>
            {config?.business.working_hours && (
              <p className="text-[11px] text-slate-500 mt-0.5">Fleet desk hours: {config.business.working_hours}</p>
            )}
            {config?.business.store_location && (
              <p className="text-[11px] text-slate-500 mt-0.5">Pickup hub: {config.business.store_location}</p>
            )}
          </div>
          <div className="text-right">
            <p className="text-[11px] text-slate-400">
              WhatsApp booking &amp; AI concierge connected to the live fleet desk.
            </p>
            <p className="mt-1">
              Autonomous Booking Platform &amp; AI System engineered by <strong className="text-zoomGold-400">AURUM AI SYSTEMS</strong>
            </p>
            <a href="/console" className="inline-block mt-2 text-[11px] text-slate-500 hover:text-zoomBlue-400 underline underline-offset-2">
              Owner / Admin console →
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
