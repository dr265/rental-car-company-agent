/**
 * Customer-site API client + shared helpers.
 *
 * All data comes from the FastAPI backend (same database the WhatsApp agent
 * uses). Nothing here invents vehicles, prices or availability — every rupee
 * shown in the UI is a server-computed quote.
 */
import { API_URL } from "@/lib/api";

/* ------------------------------------------------------------------ types */
export interface SiteVehicle {
  code: string;
  name: string;
  category: string;
  transmission: string;
  fuel: string;
  seats: number | null;
  price_6h: number | null;
  price_12h: number | null;
  price_24h: number | null;
  price_per_day: number | null;
  packages: number[];
  deposit: number;
  driver_fee_per_day: number | null;
  mileage_limit_per_day: number | null;
  extra_km_charge: number | null;
  description: string;
  location: string;
  image_url: string;
}

export interface QuoteBreakdown {
  days: number;
  duration_hours: number | null;
  price_per_day: number;
  package_price: number | null;
  base_amount: number;
  driver_fee: number;
  delivery_fee: number;
  total_estimate: number;
  deposit: number;
  currency: string;
  mileage_limit_per_day: number | null;
  extra_km_charge: number | null;
  with_driver: boolean;
}

export interface SiteConfig {
  business: {
    name: string;
    assistant_name: string;
    tagline: string;
    description: string;
    working_hours: string;
    store_location: string;
    contact_info: string;
    desk_phones: string[];
    hub_address: string;
  };
  whatsapp_number: string;
  currency: string;
  driver_fee_per_day: number;
  delivery_fee: number;
  min_lead_hours: number;
  max_booking_days: number;
  deposit_required: boolean;
  license_required: boolean;
  llm_configured: boolean;
}

export interface BookingInfo {
  reference: string;
  status: string;
  vehicle_code: string;
  vehicle_name: string;
  customer_name: string;
  customer_phone: string;
  start_at: string | null;
  end_at: string | null;
  duration_hours: number | null;
  days: number;
  drive_mode: string;
  handover: string;
  pickup_location: string;
  dropoff_location: string;
  base_amount: number;
  driver_fee: number;
  delivery_fee: number;
  total_estimate: number;
  deposit: number;
  currency: string;
  created_at: string | null;
}

export interface ConciergeMenuRow {
  id: string;
  title: string;
  description: string;
}

export interface ConciergeResult {
  session_id: string;
  language?: string;
  reply: string;
  intent?: string;
  turns?: string[];
  buttons?: { id: string; title: string }[];
  menu?: { button: string; header: string; rows: ConciergeMenuRow[] };
  carousel?: {
    body: string;
    cards: { image_id: string; image_url: string; body_text: string; buttons: { id: string; title: string }[] }[];
  };
  image_url?: string;
  image_caption?: string;
  action?: string;
  booking_form?: {
    vehicle_code: string;
    start_at: string;
    end_at: string;
    duration_hours: number | null;
    with_driver: boolean;
    handover: string;
    pickup_location: string;
  };
}

/* ------------------------------------------------------------- fetch core */
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    let message = `HTTP ${res.status}`;
    if (typeof detail === "string" && detail.trim()) message = detail;
    else if (detail && typeof detail === "object") {
      const d = detail as { message?: string; alternatives?: SiteVehicle[] };
      const err = new Error(d.message || message) as Error & { payload?: unknown };
      err.payload = detail;
      throw err;
    } else if (detail) message = JSON.stringify(detail);
    const err = new Error(message) as Error & { payload?: unknown };
    err.payload = data;
    throw err;
  }
  return data as T;
}

/* ---------------------------------------------------------------- helpers */
/** Media URLs may be same-origin relative (/media/...) — resolve for dev. */
export function mediaUrl(url: string): string {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  return `${API_URL}${url.startsWith("/") ? "" : "/"}${url}`;
}

export function money(amount: number | null | undefined, currency = "₹"): string {
  if (amount === null || amount === undefined) return "—";
  return `${currency}${Number(amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/** Local <input type=datetime-local> value → UTC ISO for the API. */
export function localInputToIso(value: string): string {
  const d = new Date(value);
  return isNaN(d.getTime()) ? "" : d.toISOString();
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  });
}

/** "today" + N days as a yyyy-mm-dd string for date inputs. */
export function isoDatePlusDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function timePlus(dateStr: string, timeStr: string, hours: number): string {
  const d = new Date(`${dateStr}T${timeStr || "10:00"}`);
  if (isNaN(d.getTime())) return "";
  d.setHours(d.getHours() + hours);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* ------------------------------------------------------------- API calls */
export async function getSiteConfig(): Promise<SiteConfig> {
  return call<SiteConfig>("/api/site/config");
}

export async function getVehicles(): Promise<{ vehicles: SiteVehicle[]; categories: string[] }> {
  return call<{ vehicles: SiteVehicle[]; categories: string[] }>("/api/site/vehicles");
}

export async function getVehicle(code: string, startIso?: string, endIso?: string) {
  const qs = startIso && endIso ? `?start_at=${encodeURIComponent(startIso)}&end_at=${encodeURIComponent(endIso)}` : "";
  return call<{ vehicle: SiteVehicle; available?: boolean; alternatives?: SiteVehicle[] }>(
    `/api/site/vehicles/${encodeURIComponent(code)}${qs}`);
}

export async function postQuote(body: {
  vehicle_code: string;
  start_at: string;
  end_at: string;
  with_driver: boolean;
  delivery: boolean;
}): Promise<{ available: boolean; quote: QuoteBreakdown | null; alternatives: SiteVehicle[] }> {
  return call("/api/site/quote", { method: "POST", body: JSON.stringify(body) });
}

export async function postBooking(body: {
  vehicle_code: string;
  start_at: string;
  end_at: string;
  with_driver: boolean;
  delivery: boolean;
  pickup_location: string;
  dropoff_location: string;
  name: string;
  phone: string;
  notes: string;
  idempotency_key: string;
}): Promise<{ booking: BookingInfo; duplicate: boolean }> {
  return call("/api/site/bookings", { method: "POST", body: JSON.stringify(body) });
}

export async function getBookingStatus(reference: string, phone: string): Promise<{ booking: BookingInfo }> {
  return call(`/api/site/bookings/${encodeURIComponent(reference)}?phone=${encodeURIComponent(phone)}`);
}

export async function postConcierge(body: {
  session_id: string;
  message: string;
  name?: string;
}): Promise<ConciergeResult> {
  return call("/api/site/concierge", { method: "POST", body: JSON.stringify(body) });
}

/* --------------------------------------------------------- WhatsApp links */
/**
 * The WhatsApp Business number for deep links. Primary source is the live
 * backend config; NEXT_PUBLIC_WA_NUMBER (baked at build time) is the fallback
 * so the links still carry the right number when the API is unreachable —
 * e.g. a static deployment whose backend is elsewhere or briefly down.
 */
export function waNumber(config: SiteConfig | null): string {
  return config?.whatsapp_number || process.env.NEXT_PUBLIC_WA_NUMBER || "";
}

/** Prefilled WhatsApp booking message — Option A deep link. */
export function waBookingLink(opts: {
  whatsappNumber: string;
  vehicle?: SiteVehicle | null;
  startIso?: string;
  endIso?: string;
  hours?: number | null;
  withDriver?: boolean;
  delivery?: boolean;
  pickupLocation?: string;
  name?: string;
  phone?: string;
}): string {
  const lines: string[] = ["Hi ZoomRideXX! 🚗"];
  if (opts.vehicle) lines.push(`I'd like to book the *${opts.vehicle.name}* (${opts.vehicle.code}).`);
  else lines.push("I'd like to inquire about renting a car.");
  if (opts.hours) lines.push(`• Package: ${opts.hours} hours`);
  if (opts.startIso) lines.push(`• Pickup: ${formatWhen(opts.startIso)}`);
  if (opts.endIso) lines.push(`• Return: ${formatWhen(opts.endIso)}`);
  lines.push(`• Mode: ${opts.withDriver ? "With chauffeur" : "Self-drive"}`);
  lines.push(`• Handover: ${opts.delivery ? "Doorstep delivery" : "Hub self-pickup"}`);
  if (opts.pickupLocation) lines.push(`• Address: ${opts.pickupLocation}`);
  if (opts.name) lines.push(`• Name: ${opts.name}`);
  if (opts.phone) lines.push(`• Phone: ${opts.phone}`);
  lines.push("Please confirm availability and next steps 🙏");
  return `https://wa.me/${opts.whatsappNumber}?text=${encodeURIComponent(lines.join("\n"))}`;
}

export function waInquiryLink(whatsappNumber: string, text?: string): string {
  const message = text || "Hi ZoomRideXX! I have a question about car rental.";
  return `https://wa.me/${whatsappNumber}?text=${encodeURIComponent(message)}`;
}
