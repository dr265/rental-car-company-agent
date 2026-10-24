"use client";

/* Website booking (Option B): pickup/return scheduling, self-drive or
   chauffeur, hub or doorstep, live server-side quote, real confirmed booking
   with an RC reference — then an optional "Continue on WhatsApp" hand-off. */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/site/icons";
import {
  localInputToIso, money, postBooking, postQuote, timePlus, waBookingLink, waNumber,
  type BookingInfo, type QuoteBreakdown, type SiteConfig, type SiteVehicle,
} from "@/lib/site";

export interface BookingPrefill {
  vehicleCode?: string;
  startAt?: string;   // datetime-local value
  hours?: number | null;
  withDriver?: boolean;
  delivery?: boolean;
  pickupLocation?: string;
}

type SubmitState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "success"; booking: BookingInfo; duplicate: boolean }
  | { phase: "error"; message: string; alternatives?: SiteVehicle[] };

function defaultPickup(minLeadHours: number): string {
  const d = new Date(Date.now() + Math.max(minLeadHours, 2) * 3600 * 1000 + 10 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function BookingModal({
  config,
  vehicles,
  prefill,
  onClose,
}: {
  config: SiteConfig | null;
  vehicles: SiteVehicle[];
  prefill: BookingPrefill;
  onClose: () => void;
}) {
  const currency = config?.currency || "₹";
  const [vehicleCode, setVehicleCode] = useState(prefill.vehicleCode || vehicles[0]?.code || "");
  const [startAt, setStartAt] = useState(prefill.startAt || defaultPickup(config?.min_lead_hours ?? 2));
  const [durationHours, setDurationHours] = useState<number>(prefill.hours ?? 24);
  const [days, setDays] = useState(1);
  const [multiDay, setMultiDay] = useState((prefill.hours ?? 24) === 0);
  const [withDriver, setWithDriver] = useState(prefill.withDriver ?? false);
  const [delivery, setDelivery] = useState(prefill.delivery ?? false);
  const [pickupLocation, setPickupLocation] = useState(prefill.pickupLocation || "");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");

  const [quoteData, setQuoteData] = useState<{ loading: boolean; quote: QuoteBreakdown | null; error: string }>({
    loading: false, quote: null, error: "",
  });
  const [submit, setSubmit] = useState<SubmitState>({ phase: "idle" });
  const idemKey = useRef<string>("");
  if (!idemKey.current && typeof crypto !== "undefined" && "randomUUID" in crypto) {
    idemKey.current = crypto.randomUUID();
  }

  const vehicle = useMemo(
    () => vehicles.find((v) => v.code === vehicleCode) || null,
    [vehicles, vehicleCode]
  );

  const endAt = useMemo(() => {
    if (!startAt) return "";
    const datePart = startAt.slice(0, 10);
    const timePart = startAt.slice(11, 16);
    if (multiDay) return timePlus(datePart, timePart, 24 * Math.max(1, days));
    return timePlus(datePart, timePart, durationHours);
  }, [startAt, durationHours, days, multiDay]);

  const minStart = useMemo(() => defaultPickup(config?.min_lead_hours ?? 2), [config]);

  /* live quote (debounced) — server computes every rupee */
  useEffect(() => {
    if (!vehicle || !startAt || !endAt || submit.phase === "success") return;
    let cancelled = false;
    setQuoteData((q) => ({ ...q, loading: true, error: "" }));
    const t = setTimeout(async () => {
      try {
        const res = await postQuote({
          vehicle_code: vehicle.code,
          start_at: localInputToIso(startAt),
          end_at: localInputToIso(endAt),
          with_driver: withDriver,
          delivery,
        });
        if (cancelled) return;
        if (!res.available) {
          setQuoteData({
            loading: false, quote: null,
            error: `${vehicle.name} is already booked for that window — pick another time or vehicle.`,
          });
        } else {
          setQuoteData({ loading: false, quote: res.quote, error: "" });
        }
      } catch (err) {
        if (!cancelled) {
          setQuoteData({ loading: false, quote: null, error: err instanceof Error ? err.message : "quote failed" });
        }
      }
    }, 400);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vehicle?.code, startAt, endAt, withDriver, delivery]);

  /* reset submit state whenever the form changes after a failure */
  useEffect(() => {
    if (submit.phase === "error") setSubmit({ phase: "idle" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vehicleCode, startAt, endAt, withDriver, delivery, name, phone]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pkgOptions = useMemo(() => {
    const opts: { hours: number; label: string }[] = [];
    for (const h of [6, 12, 24]) {
      if (!vehicle || vehicle.packages.includes(h)) {
        opts.push({ hours: h, label: h === 24 ? "24 Hours (Full Day)" : `${h} Hours` });
      }
    }
    return opts;
  }, [vehicle]);

  const clientValidation = (): string => {
    if (!vehicle) return "choose a vehicle";
    if (!name.trim() || name.trim().length < 2) return "enter your full name";
    const digits = phone.replace(/\D/g, "");
    if (digits.length < 10) return "enter a valid WhatsApp number";
    if (!startAt) return "choose a pickup time";
    if (!endAt || new Date(endAt) <= new Date(startAt)) return "the return must be after the pickup";
    return "";
  };

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!vehicle || !startAt || !endAt) return;
    const invalid = clientValidation();
    if (invalid) {
      setSubmit({ phase: "error", message: `Please ${invalid}.` });
      return;
    }
    setSubmit({ phase: "submitting" });
    try {
      const res = await postBooking({
        vehicle_code: vehicle.code,
        start_at: localInputToIso(startAt),
        end_at: localInputToIso(endAt),
        with_driver: withDriver,
        delivery,
        pickup_location: pickupLocation.trim(),
        dropoff_location: "",
        name: name.trim(),
        phone: phone.trim(),
        notes: notes.trim(),
        idempotency_key: idemKey.current,
      });
      setSubmit({ phase: "success", booking: res.booking, duplicate: res.duplicate });
    } catch (err) {
      const payload = (err as { payload?: { detail?: { alternatives?: SiteVehicle[] } } }).payload;
      const alternatives = payload?.detail?.alternatives;
      setSubmit({
        phase: "error",
        message: err instanceof Error ? err.message : "booking failed",
        alternatives,
      });
    }
  }

  const q = quoteData.quote;

  /* ------------------------------ success view ------------------------------ */
  if (submit.phase === "success") {
    const b = submit.booking;
    const waHref = waBookingLink({
      whatsappNumber: waNumber(config),
      vehicle,
      startIso: b.start_at || undefined,
      endIso: b.end_at || undefined,
      name: b.customer_name,
      phone: b.customer_phone,
    });
    return (
      <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4" role="dialog" aria-modal="true">
        <div className="glass-card rounded-xl max-w-md w-full p-6 sm:p-8 relative border border-emerald-500/40 text-center">
          <div className="w-14 h-14 rounded-full bg-emerald-500/15 text-emerald-400 flex items-center justify-center mx-auto mb-4 border border-emerald-500/30">
            <Icon name="check-circle" className="w-7 h-7" />
          </div>
          <h3 className="font-heading text-2xl font-extrabold text-white">Booking Confirmed 🎉</h3>
          <p className="text-xs text-slate-400 mt-1">
            {submit.duplicate ? "This booking was already submitted — here it is again." : "Your reservation is saved in our system."}
          </p>

          <div className="mt-4 bg-black/50 border border-slate-800 rounded-lg p-4 text-left text-xs space-y-1.5">
            <div className="flex justify-between gap-3"><span className="text-slate-400">Reference</span><strong className="font-mono text-zoomGold-400 text-sm">{b.reference}</strong></div>
            <div className="flex justify-between gap-3"><span className="text-slate-400">Vehicle</span><span className="text-white font-semibold text-right">{b.vehicle_name}</span></div>
            <div className="flex justify-between gap-3"><span className="text-slate-400">Pickup</span><span className="text-white text-right">{b.start_at ? new Date(b.start_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "numeric", minute: "2-digit", hour12: true }) : "—"}</span></div>
            <div className="flex justify-between gap-3"><span className="text-slate-400">Return</span><span className="text-white text-right">{b.end_at ? new Date(b.end_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "numeric", minute: "2-digit", hour12: true }) : "—"}</span></div>
            <div className="flex justify-between gap-3"><span className="text-slate-400">Mode</span><span className="text-white">{b.drive_mode === "chauffeur" ? "With chauffeur" : "Self-drive"} • {b.handover === "doorstep" ? "Doorstep delivery" : "Hub pickup"}</span></div>
            <div className="flex justify-between gap-3 border-t border-slate-800 pt-1.5"><span className="text-slate-400">Estimated rent</span><strong className="text-zoomGold-400">{money(b.total_estimate, b.currency)}</strong></div>
            {b.deposit > 0 && (
              <div className="flex justify-between gap-3"><span className="text-slate-400">Refundable deposit</span><span className="text-slate-200">{money(b.deposit, b.currency)} (separate)</span></div>
            )}
          </div>

          <p className="text-[11px] text-slate-400 mt-3">
            Our fleet desk will WhatsApp you on <strong className="text-slate-200">{b.customer_phone}</strong> to reconfirm handover and KYC
            {config?.business.working_hours ? ` (desk hours: ${config.business.working_hours})` : ""}.
          </p>

          <div className="grid grid-cols-2 gap-2.5 mt-5">
            <button
              onClick={onClose}
              className="w-full py-3 bg-zoomDark-800 hover:bg-slate-700 text-white font-bold text-xs uppercase tracking-wider rounded-lg transition border border-slate-700"
            >
              Done
            </button>
            <a
              href={waHref}
              target="_blank"
              rel="noreferrer"
              className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 text-black font-extrabold text-xs uppercase tracking-wider rounded-lg transition flex items-center justify-center gap-1.5"
            >
              <Icon name="message" className="w-4 h-4 fill-black text-transparent" /> Continue on WhatsApp
            </a>
          </div>
        </div>
      </div>
    );
  }

  /* ------------------------------- form view -------------------------------- */
  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Book a car"
    >
      <div className="glass-card rounded-xl max-w-lg w-full max-h-[92vh] overflow-y-auto p-6 sm:p-8 relative border border-zoomBlue-500/40">
        <button onClick={onClose} className="absolute top-4 right-4 text-slate-400 hover:text-white" aria-label="Close">
          <Icon name="x" className="w-5 h-5" />
        </button>

        <div className="mb-5">
          <span className="text-zoomBlue-400 text-xs font-bold uppercase tracking-wider">Fast Booking</span>
          <h3 className="font-heading text-2xl font-bold text-white mt-1">Book Your Car</h3>
          <p className="text-xs text-slate-400 mt-1">
            Confirmed instantly with a booking reference — pay nothing online.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          {/* vehicle */}
          <div>
            <label htmlFor="bk-vehicle" className="block text-slate-300 font-semibold mb-1">Vehicle</label>
            <select
              id="bk-vehicle"
              value={vehicleCode}
              onChange={(e) => setVehicleCode(e.target.value)}
              className="w-full bg-zoomDark-900 border border-slate-700 focus:border-zoomBlue-400 rounded px-3 py-2 text-white outline-none"
            >
              {vehicles.map((v) => (
                <option key={v.code} value={v.code}>
                  {v.name} — from {money(v.price_12h ?? v.price_24h ?? v.price_6h, currency)} / {v.price_12h ? "12h" : "24h"}
                </option>
              ))}
            </select>
          </div>

          {/* pickup */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="bk-start" className="block text-slate-300 font-semibold mb-1">
                Pickup <span className="text-slate-500">(min {config?.min_lead_hours ?? 2}h ahead)</span>
              </label>
              <input
                id="bk-start"
                type="datetime-local"
                required
                value={startAt}
                min={minStart}
                onChange={(e) => setStartAt(e.target.value)}
                className="w-full bg-zoomDark-900 border border-slate-700 focus:border-zoomBlue-400 rounded px-3 py-2 text-white outline-none"
              />
            </div>
            <div>
              <label htmlFor="bk-duration" className="block text-slate-300 font-semibold mb-1">Duration</label>
              {multiDay ? (
                <select
                  id="bk-duration"
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                  className="w-full bg-zoomDark-900 border border-slate-700 focus:border-zoomBlue-400 rounded px-3 py-2 text-white outline-none"
                >
                  {[2, 3, 4, 5, 6, 7].map((d) => (
                    <option key={d} value={d}>{d} Days (outstation)</option>
                  ))}
                </select>
              ) : (
                <select
                  id="bk-duration"
                  value={durationHours}
                  onChange={(e) => setDurationHours(Number(e.target.value))}
                  className="w-full bg-zoomDark-900 border border-slate-700 focus:border-zoomBlue-400 rounded px-3 py-2 text-white outline-none"
                >
                  {pkgOptions.map((o) => (
                    <option key={o.hours} value={o.hours}>{o.label}</option>
                  ))}
                  <option value={0} disabled hidden>—</option>
                </select>
              )}
              <button
                type="button"
                onClick={() => setMultiDay((v) => !v)}
                className="mt-1 text-[10px] text-zoomBlue-400 hover:text-white font-semibold"
              >
                {multiDay ? "← Back to 6/12/24h packages" : "Multi-day / outstation →"}
              </button>
            </div>
          </div>
          <p className="text-[10px] text-slate-500 -mt-2">
            Return: <span className="text-slate-300">{endAt ? new Date(endAt).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "numeric", minute: "2-digit", hour12: true }) : "—"}</span>
          </p>

          {/* mode + handover */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-zoomDark-900 border border-slate-800 rounded p-2.5">
              <span className="block text-[10px] uppercase font-bold text-slate-400 tracking-wider mb-1.5">Rental type</span>
              <div className="grid grid-cols-2 gap-1.5">
                <button type="button" onClick={() => setWithDriver(false)}
                  className={`py-1.5 rounded font-bold text-[11px] transition ${!withDriver ? "bg-zoomBlue-500 text-black" : "bg-black/40 text-slate-300 border border-slate-800"}`}>
                  Self-Drive
                </button>
                <button type="button" onClick={() => setWithDriver(true)}
                  className={`py-1.5 rounded font-bold text-[11px] transition ${withDriver ? "bg-zoomBlue-500 text-black" : "bg-black/40 text-slate-300 border border-slate-800"}`}>
                  Chauffeur
                </button>
              </div>
            </div>
            <div className="bg-zoomDark-900 border border-slate-800 rounded p-2.5">
              <span className="block text-[10px] uppercase font-bold text-slate-400 tracking-wider mb-1.5">Handover</span>
              <div className="grid grid-cols-2 gap-1.5">
                <button type="button" onClick={() => setDelivery(false)}
                  className={`py-1.5 rounded font-bold text-[11px] transition ${!delivery ? "bg-zoomBlue-500 text-black" : "bg-black/40 text-slate-300 border border-slate-800"}`}>
                  Hub Pickup
                </button>
                <button type="button" onClick={() => setDelivery(true)}
                  className={`py-1.5 rounded font-bold text-[11px] transition ${delivery ? "bg-zoomBlue-500 text-black" : "bg-black/40 text-slate-300 border border-slate-800"}`}>
                  Doorstep
                </button>
              </div>
            </div>
          </div>

          {delivery && (
            <div>
              <label htmlFor="bk-addr" className="block text-slate-300 font-semibold mb-1">
                Delivery address <span className="text-zoomGold-400">(+{money(config?.delivery_fee ?? 0, currency)})</span>
              </label>
              <input
                id="bk-addr"
                type="text"
                value={pickupLocation}
                onChange={(e) => setPickupLocation(e.target.value)}
                placeholder="e.g. Hotel Sunrise, Andheri West"
                className="w-full bg-zoomDark-900 border border-slate-700 focus:border-zoomBlue-400 rounded px-3 py-2 text-white outline-none"
              />
            </div>
          )}

          {/* customer */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="bk-name" className="block text-slate-300 font-semibold mb-1">Full name</label>
              <input
                id="bk-name" type="text" required minLength={2}
                value={name} onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Rahul Sharma"
                className="w-full bg-zoomDark-900 border border-slate-700 focus:border-zoomBlue-400 rounded px-3 py-2 text-white outline-none"
              />
            </div>
            <div>
              <label htmlFor="bk-phone" className="block text-slate-300 font-semibold mb-1">WhatsApp number</label>
              <input
                id="bk-phone" type="tel" required
                value={phone} onChange={(e) => setPhone(e.target.value)}
                placeholder="+91 98765 43210"
                className="w-full bg-zoomDark-900 border border-slate-700 focus:border-zoomBlue-400 rounded px-3 py-2 text-white outline-none"
              />
            </div>
          </div>
          <div>
            <label htmlFor="bk-notes" className="block text-slate-300 font-semibold mb-1">Notes (optional)</label>
            <input
              id="bk-notes" type="text" maxLength={300}
              value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="Anything the fleet desk should know"
              className="w-full bg-zoomDark-900 border border-slate-700 focus:border-zoomBlue-400 rounded px-3 py-2 text-white outline-none"
            />
          </div>

          {/* live quote */}
          <div className="p-3 bg-black/60 rounded border border-slate-800">
            {quoteData.loading && (
              <div className="flex items-center justify-between text-slate-400">
                <span>Calculating…</span>
                <span className="flex gap-1"><span className="tdot w-1.5 h-1.5 rounded-full bg-zoomBlue-400 inline-block" /><span className="tdot w-1.5 h-1.5 rounded-full bg-zoomBlue-400 inline-block" /><span className="tdot w-1.5 h-1.5 rounded-full bg-zoomBlue-400 inline-block" /></span>
              </div>
            )}
            {!quoteData.loading && quoteData.error && (
              <p className="text-amber-400 font-semibold flex items-start gap-1.5">
                <Icon name="info" className="w-4 h-4 mt-0.5 flex-shrink-0" /> {quoteData.error}
              </p>
            )}
            {!quoteData.loading && !quoteData.error && q && (
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400 uppercase font-semibold">Estimated rent</span>
                  <span className="text-xl font-bold text-zoomGold-400">{money(q.total_estimate, q.currency)}</span>
                </div>
                <div className="flex justify-between text-[10px] text-slate-500">
                  <span>
                    {q.duration_hours
                      ? `${q.duration_hours}-hour package`
                      : `${q.days} day(s) × ${money(q.price_per_day, q.currency)}`}
                    {q.driver_fee ? ` • chauffeur ${money(q.driver_fee, q.currency)}` : ""}
                    {q.delivery_fee ? ` • delivery ${money(q.delivery_fee, q.currency)}` : ""}
                  </span>
                  {q.deposit ? <span>+ {money(q.deposit, q.currency)} refundable deposit</span> : null}
                </div>
                {q.mileage_limit_per_day ? (
                  <div className="text-[10px] text-slate-500">
                    Includes {q.mileage_limit_per_day} km/day{q.extra_km_charge ? ` • ${money(q.extra_km_charge, q.currency)}/km extra` : ""}
                  </div>
                ) : null}
                <div className="text-[10px] text-slate-500">Final settlement at pickup • no online payment</div>
              </div>
            )}
          </div>

          {submit.phase === "error" && (
            <div className="p-3 bg-red-950/40 border border-red-500/30 rounded text-red-300">
              <p className="font-semibold">{submit.message}</p>
              {submit.alternatives && submit.alternatives.length > 0 && (
                <div className="mt-2">
                  <p className="text-[11px] text-red-200/80">Free for your window:</p>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {submit.alternatives.map((a) => (
                      <button
                        key={a.code} type="button"
                        onClick={() => setVehicleCode(a.code)}
                        className="px-2 py-1 rounded bg-zoomDark-800 border border-slate-700 text-[11px] text-white hover:border-zoomBlue-400"
                      >
                        {a.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <button
            type="submit"
            disabled={submit.phase === "submitting" || quoteData.loading || !quoteData.quote}
            className="w-full py-3 bg-gradient-to-r from-zoomBlue-500 to-cyan-400 text-black font-extrabold uppercase tracking-wider rounded hover:brightness-110 transition shadow-lg shadow-zoomBlue-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submit.phase === "submitting" ? "Confirming…" : "Confirm Booking"}
          </button>
          <p className="text-[10px] text-slate-500 text-center">
            By confirming you agree to the deposit &amp; KYC rules — licence + ID required at handover
            {config?.business.working_hours ? ` • Desk: ${config.business.working_hours}` : ""}.
          </p>
        </form>
      </div>
    </div>
  );
}
