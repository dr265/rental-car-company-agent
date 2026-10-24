"use client";

/* ZoomRideXX customer website (root route).
   Design language: the original index.html. Data: 100% live from the FastAPI
   backend — the same fleet, prices, bookings and AI agent that run WhatsApp. */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { SiteFooter, SiteNav } from "@/components/site/chrome";
import { Hero, type FleetFilter } from "@/components/site/hero";
import { FleetSection } from "@/components/site/fleet";
import { VehicleModal } from "@/components/site/vehicle-modal";
import { BookingModal, type BookingPrefill } from "@/components/site/booking-modal";
import { HowItWorks } from "@/components/site/how-it-works";
import { ConciergeDrawer } from "@/components/site/concierge";
import { Icon } from "@/components/site/icons";
import {
  getSiteConfig, getVehicles,
  type ConciergeResult, type SiteConfig, type SiteVehicle,
} from "@/lib/site";

export default function SitePage() {
  const [config, setConfig] = useState<SiteConfig | null>(null);
  const [vehicles, setVehicles] = useState<SiteVehicle[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FleetFilter>({ duration: "24h", category: "all" });

  const [detailsVehicle, setDetailsVehicle] = useState<SiteVehicle | null>(null);
  const [bookingPrefill, setBookingPrefill] = useState<BookingPrefill | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, fleet] = await Promise.all([
        getSiteConfig().catch(() => null),
        getVehicles(),
      ]);
      setConfig(cfg);
      setVehicles(fleet.vehicles);
      setCategories(fleet.categories);
    } catch (err) {
      setError(err instanceof Error ? err.message : "backend unreachable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openQuickBook = useCallback((v: SiteVehicle) => {
    setDetailsVehicle(null);
    setBookingPrefill({ vehicleCode: v.code });
  }, []);

  const openBookingFormFromChat = useCallback((form: NonNullable<ConciergeResult["booking_form"]>) => {
    setChatOpen(false);
    setBookingPrefill({
      vehicleCode: form.vehicle_code || undefined,
      hours: form.duration_hours ?? undefined,
      withDriver: form.with_driver,
      delivery: form.handover === "doorstep",
      pickupLocation: form.pickup_location || undefined,
    });
  }, []);

  const vehicleByCode = useMemo(() => {
    const map = new Map<string, SiteVehicle>();
    vehicles.forEach((v) => map.set(v.code, v));
    return map;
  }, [vehicles]);

  return (
    <div className="zsite">
      <SiteNav config={config} onOpenConcierge={() => setChatOpen(true)} />

      <Hero
        config={config}
        vehicles={vehicles}
        filter={filter}
        onFilterChange={setFilter}
        onQuickBook={openQuickBook}
        onDetails={setDetailsVehicle}
      />

      <FleetSection
        config={config}
        vehicles={vehicles}
        categories={categories}
        filter={filter}
        onFilterChange={setFilter}
        loading={loading}
        error={error}
        onRetry={load}
        onQuickBook={openQuickBook}
        onDetails={setDetailsVehicle}
      />

      <HowItWorks />

      <SiteFooter config={config} />

      {/* floating concierge trigger */}
      <div className="fixed bottom-6 right-6 z-40 flex items-center gap-3">
        <div className="hidden sm:flex bg-black/90 border border-zoomBlue-500/50 text-zoomBlue-300 text-xs px-3.5 py-2 rounded-full shadow-2xl animate-pulse">
          <span>🚗 Need a car right now? Ask Karan!</span>
        </div>
        <button
          onClick={() => setChatOpen(true)}
          aria-label="Open AI concierge chat"
          className="bg-gradient-to-r from-zoomBlue-500 to-cyan-500 text-black p-4 rounded-full shadow-2xl hover:scale-105 transition flex items-center justify-center"
        >
          <Icon name="message" className="w-6 h-6" />
        </button>
      </div>

      {detailsVehicle && (
        <VehicleModal
          config={config}
          vehicle={detailsVehicle}
          onClose={() => setDetailsVehicle(null)}
          onBook={openQuickBook}
        />
      )}

      {bookingPrefill && (
        <BookingModal
          config={config}
          vehicles={vehicles}
          prefill={bookingPrefill}
          onClose={() => setBookingPrefill(null)}
        />
      )}

      <ConciergeDrawer
        open={chatOpen}
        config={config}
        onClose={() => setChatOpen(false)}
        onOpenBookingForm={openBookingFormFromChat}
      />
    </div>
  );
}
