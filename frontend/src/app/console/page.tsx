'use client';

/* Owner console (admin) — lives at /console. The customer-facing website is
   the root route (src/app/page.tsx). This is the same single-page console,
   unchanged, served as part of the same static export. */

import React, { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { api, getAdminToken, setAdminToken } from "@/lib/api";
import { Container, Eyebrow, MicButton, Nav, SectionHead, useReveal } from "@/components/sara";
import ConnectionPanel from "@/components/ConnectionPanel";
import DashboardPanel from "@/components/DashboardPanel";
import KnowledgePanel from "@/components/KnowledgePanel";
import PersonaPanel from "@/components/PersonaPanel";
import FleetPanel from "@/components/FleetPanel";
import BookingsPanel from "@/components/BookingsPanel";
import OwnerInbox from "@/components/OwnerInbox";
import OwnerAssistant from "@/components/OwnerAssistant";
import MediaPanel from "@/components/MediaPanel";
import ImageAlbum, { type AlbumImage } from "@/components/ImageAlbum";
import { LANGUAGE_BCP47, useLanguages } from "@/components/LanguagePicker";
import { FlashHost } from "@/components/flash";

/* -------------------------------------------------------------------------- */
/*  Live backend wiring                                                        */
/* -------------------------------------------------------------------------- */
interface EngineHealth {
  status: string;
  kapso: { api_key_set: boolean; phone_number_id_set: boolean; webhook_secret_set: boolean };
  llm_configured: boolean;
  counts: {
    customers: number;
    conversations: number;
    messages: number;
    documents: number;
    products: number;
    categories: number;
    orders: number;
    faqs: number;
    vehicles: number;
    bookings: number;
  };
}

function useEngineHealth() {
  const [health, setHealth] = useState<EngineHealth | null>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);

  const check = useCallback(() => {
    api<EngineHealth>("/api/health")
      .then((h) => { setHealth(h); setReachable(true); })
      .catch(() => { setHealth(null); setReachable(false); });
  }, []);

  useEffect(() => {
    check();
    const t = setInterval(check, 10000);
    return () => clearInterval(t);
  }, [check]);

  return { health, reachable, refresh: check };
}

/* -------------------------------------------------------------------------- */
/*  RUN / PAUSE chip — state lives on the backend, survives restarts            */
/* -------------------------------------------------------------------------- */
function AgentRunChip() {
  const [running, setRunning] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () =>
    api<{ running: boolean }>("/api/whatsapp/run-state")
      .then((d) => setRunning(Boolean(d.running)))
      .catch(() => {});
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, []);
  const toggle = async () => {
    if (busy || running === null) return;
    setBusy(true);
    try {
      const d = await api<{ running: boolean }>(
        `/api/whatsapp/${running ? "pause" : "run"}`, { method: "POST" }
      );
      setRunning(Boolean(d.running));
    } catch { /* keep prior state */ } finally { setBusy(false); }
  };
  return (
    <button
      onClick={toggle}
      disabled={running === null || busy}
      title={
        running
          ? "Agent is live — click to pause (customers get no replies until you run it again)"
          : "Agent is paused — click to run (customers are answered automatically)"
      }
      className={`mono inline-flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] transition-colors ${
        running === false
          ? "border-white/15 bg-[var(--ink-3)] text-[var(--dim)]"
          : "border-[var(--green)]/40 bg-[var(--green)]/10 text-[var(--green)]"
      } ${busy ? "opacity-60" : ""}`}
    >
      <span
        className={`h-2 w-2 rounded-full ${
          running === null ? "bg-[#c9a961]" : running ? "bg-[#2fbf71]" : "bg-[#6b727d]"
        }`}
        aria-hidden
      />
      AGENT {running === null ? "…" : running ? "RUNNING" : "PAUSED"}
      <span aria-hidden>{running === null ? "" : running ? "⏸" : "▶"}</span>
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/*  Hero — real status pills + live WhatsApp-style phone                       */
/* -------------------------------------------------------------------------- */
function Hero({
  health,
  reachable,
  onOpenConsole,
}: {
  health: EngineHealth | null;
  reachable: boolean | null;
  onOpenConsole: () => void;
}) {
  return (
    <section className="grain relative overflow-hidden pt-28 sm:pt-36">
      <div className="grid-bg absolute inset-0" aria-hidden />
      <div className="absolute left-1/2 top-0 h-[600px] w-[900px] -translate-x-1/2 -translate-y-1/3 rounded-full bg-[radial-gradient(closest-side,rgba(201,169,97,.10),transparent)]" aria-hidden />
      <Container className="relative grid items-center gap-12 lg:grid-cols-[1.05fr_1fr] lg:gap-6">
        <div className="max-w-[560px]">
          <div data-reveal>
            <Eyebrow>WhatsApp rental desk · Kapso · live fleet</Eyebrow>
          </div>
          <h1 className="serif mt-5 text-[2.9rem] leading-[1.02] sm:text-[3.9rem] lg:text-[4.4rem]" data-reveal data-delay="60">
            The rental fleet that answers on WhatsApp <em className="text-[var(--brass)]">before your customer calls.</em>
          </h1>
          <p className="mt-6 max-w-[500px] text-[16px] leading-relaxed text-[var(--muted)]" data-reveal data-delay="120">
            ZoomRideXX Car Rentals answers in English or Hindi, shows real cars from the live
            fleet with their 6h / 12h / 24h packages, collects KYC and takes confirmed bookings —
            while you run the fleet, availability and booking status from the console below.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3" data-reveal data-delay="180">
            <button onClick={onOpenConsole} className="btn-primary rounded-full px-5 py-3 text-[14.5px] font-semibold">
              Open the console
            </button>
          </div>

          {/* Live engine status — real data from /api/health */}
          <div className="mt-8 flex flex-wrap items-center gap-3" data-reveal data-delay="220">
            <span className="mono inline-flex items-center gap-2 rounded-full border border-white/10 bg-[var(--ink-2)] px-3 py-1.5 text-[11px]">
              <span
                className={`status-dot h-2 w-2 rounded-full ${
                  reachable === null ? "bg-[#c9a961]" : reachable && health?.status === "ok" ? "bg-[#2fbf71]" : "bg-[#e05555]"
                }`}
                aria-hidden
              />
              ENGINE {reachable === null ? "CHECKING…" : reachable && health?.status === "ok" ? "ONLINE" : "UNREACHABLE"}
            </span>
            <span className="mono inline-flex items-center gap-2 rounded-full border border-white/10 bg-[var(--ink-2)] px-3 py-1.5 text-[11px]">
              <span className={`h-2 w-2 rounded-full ${health?.llm_configured ? "bg-[#2fbf71]" : "bg-[#e05555]"}`} aria-hidden />
              LLM CHAIN {health?.llm_configured ? "READY" : "KEYS MISSING"}
            </span>
            <span className="mono inline-flex items-center gap-2 rounded-full border border-white/10 bg-[var(--ink-2)] px-3 py-1.5 text-[11px]">
              <span
                className={`h-2 w-2 rounded-full ${
                  health?.kapso.api_key_set && health?.kapso.phone_number_id_set ? "bg-[#2fbf71]" : "bg-[#e05555]"
                }`}
                aria-hidden
              />
              KAPSO {health?.kapso.api_key_set && health?.kapso.phone_number_id_set ? "CONFIGURED" : "ENV KEYS PENDING"}
            </span>
            <span className="mono inline-flex items-center gap-2 rounded-full border border-white/10 bg-[var(--ink-2)] px-3 py-1.5 text-[11px]">
              <span className="h-2 w-2 rounded-full bg-[#c9a961]" aria-hidden />
              FLEET {health?.counts.vehicles ?? "—"} · BOOKINGS {health?.counts.bookings ?? "—"}
            </span>
            <AgentRunChip />
          </div>
        </div>
        <div className="flex justify-center" data-reveal data-delay="150">
          <LivePhoneChat />
        </div>
      </Container>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-[var(--ink)]" aria-hidden />
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/*  Live WhatsApp-style chat — real engine turns via the simulator endpoint     */
/* -------------------------------------------------------------------------- */
type LangButton = { id: string; title: string };
type MenuRow = { id: string; title: string; description?: string };
type CarouselCard = {
  image_id?: string;
  image_url?: string;
  body_text?: string;
  buttons?: LangButton[];
};

type ChatMsg = {
  role: "guest" | "agent";
  content: string;
  meta?: string;
  /** the picture WhatsApp would deliver — rendered inline, as the customer sees it */
  imageUrl?: string;
  imageCaption?: string;
  /** several pictures sent together (the fleet gallery) — one swipeable album */
  images?: AlbumImage[];
  /** the native WhatsApp fleet carousel (horizontal, swipeable cards) */
  carousel?: { body?: string; cards: CarouselCard[] };
};

interface SimReply {
  reply: string; intent: string; escalate: boolean;
  language?: string; buttons?: LangButton[]; error?: string;
  image_id?: string; image_url?: string; image_caption?: string;
  images?: AlbumImage[];
  menu?: { button: string; header?: string; rows: MenuRow[] } | null;
  carousel?: { body?: string; cards: CarouselCard[] } | null;
}

function LivePhoneChat() {
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      role: "agent",
      content:
        "Hi! 👋 This is the live ZoomRideXX booking assistant. Try it exactly as a customer would — say Hi, pick a car and take it through to a confirmed booking.",
      meta: "in-app tester · real engine · not WhatsApp",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [langButtons, setLangButtons] = useState<LangButton[] | null>(null);
  const [menu, setMenu] = useState<NonNullable<SimReply["menu"]> | null>(null);
  const [activeLang, setActiveLang] = useState("");
  // language pills come from the backend registry (/api/languages) — the same
  // list the WhatsApp buttons and the owner console use, so nothing drifts
  const languagePills = useLanguages();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const appendReply = (data: SimReply) => {
    setLangButtons(data.buttons ?? null);
    setMenu(data.menu ?? null);
    if (data.language) setActiveLang(data.language);
    const album: AlbumImage[] = (data.images ?? []).filter((img) => img.url);
    if (!album.length && data.image_url) {
      album.push({
        id: data.image_id,
        url: data.image_url,
        caption: data.image_caption,
        label: data.image_caption,
      });
    }
    setMessages((m) => [
      ...m,
      {
        role: "agent",
        content: (data.error ? `⚠ ${data.error}` : data.reply) || "",
        imageUrl: album.length === 1 ? album[0].url : undefined,
        imageCaption: album.length === 1 ? album[0].caption : undefined,
        images: album.length > 1 ? album : undefined,
        carousel: data.carousel?.cards?.length ? data.carousel : undefined,
        meta: `intent: ${data.intent}${data.escalate ? " · ⚠ escalate_to_human" : ""}${
          data.language ? ` · lang: ${data.language}` : ""
        }${data.image_id ? ` · image: ${data.image_id}` : ""}`,
      },
    ]);
  };

  const send = async (raw?: string) => {
    // prefer an explicit argument, then the live DOM value, then React state —
    // so the send button always works regardless of how the text was entered
    const text = (raw ?? inputRef.current?.value ?? input).trim();
    if (!text || busy) return;
    setInput("");
    if (inputRef.current) inputRef.current.value = "";
    setMessages((m) => [...m, { role: "guest", content: text }]);
    setBusy(true);
    try {
      const data = await api<SimReply>("/api/whatsapp/simulate", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      appendReply(data);
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: "agent",
          content: "⚠ Cannot reach the agent backend. Is the backend running on port 8022?",
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const sendButton = async (b: LangButton) => {
    if (busy) return;
    setLangButtons(null);
    setMenu(null);
    setMessages((m) => [...m, { role: "guest", content: b.title }]);
    setBusy(true);
    try {
      const data = await api<SimReply>("/api/whatsapp/simulate", {
        method: "POST",
        body: JSON.stringify({ button_id: b.id }),
      });
      appendReply(data);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "agent", content: "⚠ Cannot reach the agent backend. Is the backend running on port 8022?" },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const sendMenuTap = async (row: MenuRow) => {
    if (busy) return;
    setLangButtons(null);
    setMenu(null);
    await sendButton({ id: row.id, title: row.title });
  };

  const reset = async () => {
    setLangButtons(null);
    setMenu(null);
    setActiveLang("");
    try {
      await api("/api/whatsapp/simulate", { method: "DELETE" });
    } catch { /* backend down — still clear locally */ }
    setMessages([{ role: "agent", content: "Session reset. New conversation — how can I help?" }]);
  };

  return (
    <div className="shadow-device relative h-[560px] w-[272px] shrink-0 rounded-[40px] bg-[#0a0a0c] p-[9px]">
      <div className="metal-edge pointer-events-none absolute inset-0 rounded-[40px] opacity-70" aria-hidden />
      <div className="relative flex h-full w-full flex-col overflow-hidden rounded-[32px] bg-[#0b141a]">
        <div className="absolute left-1/2 top-2.5 z-10 h-[26px] w-[92px] -translate-x-1/2 rounded-full bg-black" aria-hidden />
        <div className="mono flex items-center justify-between px-6 pt-3 text-[10px] text-[#cfd6da]">
          <span>9:41</span>
          <span className="flex items-center gap-1.5">
            <span className="status-dot h-1.5 w-1.5 rounded-full bg-[#2fbf71]" aria-hidden />
            <span className="tracking-tight">live</span>
          </span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2.5 border-b border-white/5 bg-[#1f2c34] px-3 py-2.5">
          <div className="grid h-8 w-8 place-items-center rounded-full bg-[var(--brass)] text-[13px] font-semibold text-[#1d1608]">Z</div>
          <div className="min-w-0 leading-tight">
            <div className="flex items-center gap-1 text-[13px] font-medium text-[#e9edef]">
              ZoomRideXX Car Rentals
              <svg width="12" height="12" viewBox="0 0 24 24" aria-label="verified"><circle cx="12" cy="12" r="11" fill="#25d366" /><path d="M7 12.5l3 3 7-7" stroke="#0b141a" strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <div className="truncate text-[10.5px] text-[#8696a0]">AI assistant · replies instantly</div>
          </div>
          <button
            onClick={reset}
            className="mono ml-auto rounded-md border border-white/10 px-1.5 py-1 text-[9px] text-[#8696a0] transition-colors hover:border-white/25 hover:text-[#e9edef]"
            title="Reset tester session"
          >
            reset
          </button>
        </div>
        {/* the active conversation language, switchable at any point */}
        <div className="flex items-center gap-1.5 overflow-x-auto border-b border-white/5 bg-[#111b21] px-3 py-2">
          <span className="mono shrink-0 text-[9px] uppercase tracking-wider text-[#8696a0]">
            {activeLang ? `lang: ${activeLang}` : "lang: —"}
          </span>
          <div className="ml-auto flex shrink-0 gap-1">
            {languagePills.map((l) => (
              <button
                key={l.code}
                type="button"
                disabled={busy}
                onClick={() => sendButton({ id: `lang_${l.code}`, title: l.native || l.label })}
                aria-pressed={activeLang === l.code}
                className={`rounded-full border px-2 py-0.5 text-[10.5px] transition-colors disabled:opacity-50 ${
                  activeLang === l.code
                    ? "border-[#25d366]/60 bg-[#25d366]/15 text-[#25d366]"
                    : "border-white/10 text-[#8696a0] hover:border-white/25 hover:text-[#e9edef]"
                }`}
              >
                {l.native || l.label}
              </button>
            ))}
          </div>
        </div>
        <div
          ref={scrollRef}
          className="flex-1 space-y-2 overflow-y-auto px-3 pt-3"
          style={{
            backgroundImage: "radial-gradient(rgba(255,255,255,.035) 1px, transparent 1px)",
            backgroundSize: "14px 14px",
          }}
        >
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "guest" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[86%] rounded-xl px-3 py-2 text-[12.5px] leading-[1.45] shadow-[0_1px_1px_rgba(0,0,0,.35)] whitespace-pre-line ${
                  m.role === "guest"
                    ? "rounded-tr-sm bg-[#005c4b] text-[#e9fdf4]"
                    : "rounded-tl-sm bg-[#1f2c34] text-[#e9edef]"
                }`}
              >
                {/* several pictures at once — swipe through them like a gallery */}
                {m.images && m.images.length > 0 && (
                  <ImageAlbum images={m.images} className="mb-1.5 w-[210px]" />
                )}
                {/* the actual image that goes out on WhatsApp, rendered here */}
                {m.imageUrl && (
                  <figure className="mb-1.5">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={m.imageUrl}
                      alt={m.imageCaption || "sent image"}
                      className="w-full rounded-lg bg-black/30 object-contain"
                    />
                    {m.imageCaption && (
                      <figcaption className="pt-1 text-[11px] text-[#cfd6da]">
                        {m.imageCaption}
                      </figcaption>
                    )}
                  </figure>
                )}
                {m.content}
                {m.carousel && m.carousel.cards.length > 0 && (
                  <div className="-mx-1 mt-1.5 flex snap-x gap-2 overflow-x-auto pb-1.5">
                    {m.carousel.cards.map((card, ci) => (
                      <div
                        key={`${ci}-${card.image_id ?? card.body_text ?? "car"}`}
                        className="w-[150px] shrink-0 snap-start overflow-hidden rounded-lg bg-[#111b21]"
                      >
                        {card.image_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={card.image_url}
                            alt={card.body_text?.split("\n")[0] || "car"}
                            className="h-[88px] w-full bg-black/30 object-cover"
                          />
                        ) : null}
                        <div className="p-1.5">
                          <div className="whitespace-pre-line text-[10.5px] leading-[1.4] text-[#e9edef]">
                            {card.body_text}
                          </div>
                          <div className="mt-1.5 space-y-1">
                            {card.buttons?.map((b, bi) => (
                              <button
                                key={b.id}
                                type="button"
                                disabled={busy}
                                onClick={() => sendButton(b)}
                                className={`block w-full rounded-md px-1.5 py-1 text-[10px] font-medium transition-colors disabled:opacity-50 ${
                                  bi === 0
                                    ? "bg-[#25d366] text-[#0b141a] hover:bg-[#2ee674]"
                                    : "border border-[#25d366]/50 text-[#25d366] hover:bg-[#25d366]/10"
                                }`}
                              >
                                {b.title}
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {m.meta && (
                  <div className="mono mt-1.5 text-[9px] text-[#8696a0]">{m.meta}</div>
                )}
              </div>
            </div>
          ))}
          {langButtons && !busy && (
            <div className="flex flex-wrap justify-end gap-1.5 px-1">
              {langButtons.map((b) => (
                <button
                  key={b.id}
                  onClick={() => sendButton(b)}
                  className="rounded-full border border-[#25d366]/50 bg-[#0b141a] px-3 py-1.5 text-[11.5px] font-medium text-[#25d366] transition-colors hover:bg-[#25d366]/10"
                >
                  {b.title}
                </button>
              ))}
            </div>
          )}
          {menu && !busy && (
            <div className="mx-0.5 rounded-xl border border-[#25d366]/30 bg-[#111b21] p-1.5 shadow-[0_2px_6px_rgba(0,0,0,.4)]">
              <div className="mono px-2 pb-1 pt-0.5 text-[9px] uppercase tracking-wider text-[#8696a0]">
                {menu.button || "Browse options"}
              </div>
              {menu.rows.map((r) => (
                <button
                  key={r.id}
                  onClick={() => sendMenuTap(r)}
                  className="block w-full rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-[#25d366]/10"
                >
                  <span className="block text-[12px] font-medium text-[#e9edef]">{r.title}</span>
                  {r.description ? (
                    <span className="block text-[10px] text-[#8696a0]">{r.description}</span>
                  ) : null}
                </button>
              ))}
            </div>
          )}
          {busy && (
            <div className="flex justify-start">
              <div className="flex items-center gap-1 rounded-xl rounded-tl-sm bg-[#1f2c34] px-3 py-2.5" aria-label="Agent is typing">
                <span className="dot h-1.5 w-1.5 rounded-full bg-[#8696a0]" />
                <span className="dot h-1.5 w-1.5 rounded-full bg-[#8696a0]" />
                <span className="dot h-1.5 w-1.5 rounded-full bg-[#8696a0]" />
              </div>
            </div>
          )}
        </div>
        <form
          className="flex items-center gap-2 bg-[#0b141a] px-3 pb-5 pt-2"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type as a customer…"
            aria-label="Customer message"
            className="flex-1 rounded-full bg-[#1f2c34] px-3 py-2 text-[12px] text-[#e9edef] placeholder-[#8696a0] focus:outline-none"
          />
          <MicButton
            lang={LANGUAGE_BCP47[activeLang] || "en-IN"}
            onResult={(t) => send(t)}
            busy={busy}
          />
          <button
            type="submit"
            disabled={busy}
            aria-label="Send"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#00a884] transition-opacity disabled:opacity-50"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="#06130c"><path d="M3 11l18-8-8 18-2-8-8-2z" /></svg>
          </button>
        </form>
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(115deg,rgba(255,255,255,.09),rgba(255,255,255,0)_38%)]" aria-hidden />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Console tabs                                                               */
/* -------------------------------------------------------------------------- */
type Tab =
  | "dash" | "chat" | "bookings" | "fleet"
  | "owner" | "knowledge" | "persona" | "media" | "channels";

/** Admin token padlock: set/clear the X-Admin-Token sent with every API call.
    Needed when the backend runs with ADMIN_AUTH_REQUIRED=1. */
function AdminTokenChip() {
  const [token, setToken] = useState<string>("");
  const [hasToken, setHasToken] = useState<boolean>(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setToken(getAdminToken());
    setHasToken(Boolean(getAdminToken()));
  }, []);

  const save = () => {
    setAdminToken(token);
    setHasToken(Boolean(token.trim()));
    setOpen(false);
  };

  return (
    <span className="relative inline-block">
      <button
        onClick={() => setOpen((v) => !v)}
        title={hasToken ? "Admin token is set" : "Set the admin API token (for ADMIN_AUTH_REQUIRED=1)"}
        className={`rounded-full px-3.5 py-2.5 text-[12.5px] font-medium border transition-colors ${
          hasToken
            ? "border-emerald-400/40 text-emerald-300"
            : "border-white/10 text-[var(--muted)] hover:text-[var(--ivory)]"
        }`}
      >
        {hasToken ? "🔓 Token set" : "🔒 Admin token"}
      </button>
      {open && (
        <div className="absolute right-0 top-12 z-50 w-72 rounded-xl border border-white/10 bg-[#10151c] p-3 shadow-device">
          <label htmlFor="admin-token-input" className="mono block text-[10px] uppercase tracking-wider text-[var(--dim)]">
            ADMIN_API_TOKEN (backend/.env)
          </label>
          <input
            id="admin-token-input"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="paste the shared token"
            className="mt-2 w-full rounded-md border border-white/10 bg-[#0d1117] px-3 py-2 text-[13px] text-[var(--ivory)] outline-none focus:border-[var(--brass)]"
          />
          <div className="mt-2 flex gap-2">
            <button onClick={save} className="btn-primary rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold">Save</button>
            <button
              onClick={() => { setToken(""); setAdminToken(""); setHasToken(false); setOpen(false); }}
              className="rounded-full border border-white/10 px-3.5 py-1.5 text-[12.5px] text-[var(--muted)] hover:text-[var(--ivory)]"
            >
              Clear
            </button>
          </div>
          <p className="mt-2 text-[10.5px] leading-relaxed text-[var(--dim)]">
            Only needed when ADMIN_AUTH_REQUIRED=1. Stored in this browser only.
          </p>
        </div>
      )}
    </span>
  );
}

function ControlPanel({ onLogout }: { onLogout: () => void }) {
  const [tab, setTab] = useState<Tab>("dash");

  const tabBtn = (t: Tab, label: string) => (
    <button
      key={t}
      onClick={() => setTab(t)}
      className={`rounded-full px-3.5 py-2.5 text-[12.5px] font-medium transition-colors ${
        tab === t ? "bg-jewel text-[#2a0b10]" : "border border-white/10 text-[var(--muted)] hover:text-[var(--ivory)]"
      }`}
    >
      {label}
    </button>
  );

  return (
    <section id="console" className="relative border-t border-white/5 bg-[var(--ink-2)] py-24 sm:py-32">
      <div className="absolute left-1/2 top-0 h-[400px] w-[700px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(224,138,46,.10),transparent)]" aria-hidden />
      <Container className="relative">
        <SectionHead
          eyebrow="ZoomRideXX fleet console"
          title={<>Run your car rental from one console.</>}
          body="Watch live customer conversations, manage the real fleet and its 6h / 12h / 24h packages, take bookings through their real lifecycle, publish rental rules and keep the Kapso connection healthy — every value is read live from the backend."
        />

        <div className="mt-10 flex flex-wrap items-center gap-2" data-reveal>
          {tabBtn("dash", "📟 Dashboard")}
          {tabBtn("chat", "💬 Owner chat")}
          {tabBtn("bookings", "🧾 Bookings")}
          {tabBtn("fleet", "🚗 Fleet")}
          {tabBtn("owner", "🤖 Ask the agent")}
          {tabBtn("knowledge", "📚 Knowledge")}
          {tabBtn("persona", "💼 Persona")}
          {tabBtn("media", "🖼️ Images")}
          <span className="ml-auto flex items-center gap-2">
            <AdminTokenChip />
            <button
              onClick={onLogout}
              title="End this console session"
              className="rounded-full border border-white/10 px-3.5 py-2.5 text-[12.5px] font-medium text-[var(--muted)] transition-colors hover:border-red-400/40 hover:text-red-300"
            >
              ⏏ Log out
            </button>
          </span>
          {tabBtn("channels", "📞 Connection")}
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-[#10151c] p-4 sm:p-6 lg:p-8" data-reveal data-delay="80">
          {tab === "dash" && <DashboardPanel />}
          {tab === "chat" && <OwnerInbox />}
          {tab === "bookings" && <BookingsPanel />}
          {tab === "fleet" && <FleetPanel />}
          {tab === "owner" && <OwnerAssistant />}
          {tab === "knowledge" && <KnowledgePanel />}
          {tab === "persona" && <PersonaPanel />}
          {tab === "media" && <MediaPanel />}
          {tab === "channels" && <ConnectionPanel />}
        </div>

        <FlashHost />
      </Container>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

/** Login gate for the owner console. Credentials live in backend/.env
    (ADMIN_EMAIL / ADMIN_PASSWORD); a successful login stores the issued admin
    token and is re-verified against /api/admin/verify on load. */
const AUTH_FLAG_KEY = "zr-admin-authed";

function useAdminAuth() {
  const [state, setState] = useState<"checking" | "login" | "authed">("checking");

  const check = useCallback(async () => {
    const token = getAdminToken();
    const flagged = typeof window !== "undefined" && window.localStorage.getItem(AUTH_FLAG_KEY) === "1";
    if (!token || !flagged) {
      setState("login");
      return;
    }
    try {
      const res = await api<{ valid: boolean; mode: string }>("/api/admin/verify", { method: "POST" });
      setState(res.valid ? "authed" : "login");
      if (!res.valid) window.localStorage.removeItem(AUTH_FLAG_KEY);
    } catch {
      // backend unreachable: keep the local session rather than locking the owner out
      setState("authed");
    }
  }, []);

  useEffect(() => { check(); }, [check]);
  return { state, setState };
}

function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await api<{ ok: boolean; token: string; email: string; backend_enforced: boolean }>(
        "/api/admin/login",
        { method: "POST", body: JSON.stringify({ email, password }) },
      );
      setAdminToken(res.token);
      window.localStorage.setItem(AUTH_FLAG_KEY, "1");
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sara grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm rounded-3xl border border-white/10 bg-[#10151c] p-8 shadow-device">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-md bg-[var(--brass)] text-[15px] font-semibold text-[var(--ink)]">Z</span>
          <div>
            <p className="text-[15px] font-medium tracking-tight text-[var(--ivory)]">ZoomRideXX Console</p>
            <p className="text-[11px] text-[var(--dim)]">Owner &amp; staff sign-in</p>
          </div>
        </div>

        <form onSubmit={submit} className="mt-7 space-y-4">
          <div>
            <label htmlFor="admin-email" className="mono block text-[10px] uppercase tracking-wider text-[var(--dim)]">Email</label>
            <input
              id="admin-email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="mt-1.5 w-full rounded-md border border-white/10 bg-[#0d1117] px-3 py-2.5 text-[14px] text-[var(--ivory)] outline-none focus:border-[var(--brass)]"
            />
          </div>
          <div>
            <label htmlFor="admin-password" className="mono block text-[10px] uppercase tracking-wider text-[var(--dim)]">Password</label>
            <input
              id="admin-password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••"
              className="mt-1.5 w-full rounded-md border border-white/10 bg-[#0d1117] px-3 py-2.5 text-[14px] text-[var(--ivory)] outline-none focus:border-[var(--brass)]"
            />
          </div>

          {error && (
            <p className="rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 text-[12.5px] text-red-300">{error}</p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="btn-primary w-full rounded-full py-2.5 text-[14px] font-semibold disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-5 text-center text-[11px] leading-relaxed text-[var(--dim)]">
          <Link href="/" className="text-[var(--muted)] underline underline-offset-2 hover:text-[var(--ivory)]">← Back to the website</Link>
          <br />
          Credentials are set in <span className="mono">backend/.env</span> (ADMIN_EMAIL / ADMIN_PASSWORD).
        </p>
      </div>
    </div>
  );
}

export default function WhatsAppAgentPage() {
  const { state, setState } = useAdminAuth();

  if (state === "checking") {
    return (
      <div className="sara grid min-h-screen place-items-center">
        <p className="mono text-[12px] text-[var(--dim)]">Checking session…</p>
      </div>
    );
  }
  if (state === "login") {
    return <LoginScreen onSuccess={() => setState("authed")} />;
  }
  // The console is its own component so useReveal()'s one-shot observer runs
  // AFTER the reveal targets exist — mounting it at page level (while the
  // login gate is showing) left every section stuck invisible.
  return <ConsoleHome onLogout={() => {
    window.localStorage.removeItem(AUTH_FLAG_KEY);
    setAdminToken("");
    setState("login");
  }} />;
}

function ConsoleHome({ onLogout }: { onLogout: () => void }) {
  const { health, reachable } = useEngineHealth();
  useReveal();

  const openConsole = () => {
    document.getElementById("console")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="sara relative">
      <Nav
        links={[["Console", "#console"], ["Website", "/"], ["Docs", "/docs"]]}
        subtitle="ZoomRideXX Car Rentals AI Assistant"
      />
      <main>
        <Hero health={health} reachable={reachable} onOpenConsole={openConsole} />
        <ControlPanel onLogout={onLogout} />
      </main>
      <footer className="border-t border-white/5 py-10">
        <Container className="mono flex flex-wrap items-center gap-x-6 gap-y-2 text-[10.5px] text-[var(--dim)]">
          <span>BACKEND :8022</span>
          <span>CONSOLE :8022</span>
          <span>KAPSO WHATSAPP TRANSPORT</span>
          <span>LLM FAILOVER CHAIN</span>
          <span className="ml-auto">LIVE FLEET, BOOKINGS & AVAILABILITY — NO DEMO DATA</span>
        </Container>
      </footer>
    </div>
  );
}
