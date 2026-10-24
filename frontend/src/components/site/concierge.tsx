"use client";

/* AI Concierge drawer — a real chat with the ZoomRideXX agent (the SAME brain
   that answers WhatsApp), grounded in the live fleet. Suggestions, car photos
   and tappable follow-ups come from the backend; "book" intents hand the
   visitor to the real booking form prefilled. */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/site/icons";
import { mediaUrl, postConcierge, waNumber, type ConciergeResult, type SiteConfig } from "@/lib/site";

interface ChatMsg {
  role: "user" | "agent";
  text: string;
  time: number;
  images?: { url: string; caption?: string }[];
  suggestions?: string[];
  menuRows?: string[];
  openBooking?: ConciergeResult["booking_form"];
}

const WELCOME: ChatMsg = {
  role: "agent",
  text:
    "Namaste! 🚗 I'm Karan, the ZoomRideXX concierge — the same assistant that runs our WhatsApp desk.\n\nAsk me about any car, rates, deposits, or say \"book the Thar Roxx for tomorrow 10am\".",
  time: 0,
};

const QUICK_CHIPS = [
  "Thar Roxx 24 hours rent?",
  "Show SUVs",
  "Deposit & documents for self-drive",
  "Book Swift for tomorrow 10am",
];

export function ConciergeDrawer({
  open,
  config,
  onClose,
  onOpenBookingForm,
}: {
  open: boolean;
  config: SiteConfig | null;
  onClose: () => void;
  onOpenBookingForm: (prefill: NonNullable<ConciergeResult["booking_form"]>) => void;
}) {
  const [messages, setMessages] = useState<ChatMsg[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<string>("");
  if (!sessionRef.current && typeof window !== "undefined") {
    sessionRef.current =
      window.localStorage.getItem("zr-site-session") ||
      (() => {
        const id = `s${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
        window.localStorage.setItem("zr-site-session", id);
        return id;
      })();
  }

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pending, open]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || pending) return;
      setInput("");
      setMessages((m) => [...m, { role: "user", text: trimmed, time: Date.now() }]);
      setPending(true);
      try {
        const res = await postConcierge({
          session_id: sessionRef.current,
          message: trimmed,
        });
        const suggestions = [
          ...(res.buttons || []).map((b) => b.title),
          ...(res.menu?.rows || []).slice(0, 4).map((r) => r.title),
        ].filter(Boolean);
        const images = [
          ...(res.image_url ? [{ url: res.image_url, caption: res.image_caption }] : []),
          ...(res.carousel?.cards || []).map((c) => ({ url: c.image_url, caption: c.body_text })),
        ];
        setMessages((m) => [
          ...m,
          {
            role: "agent",
            text: res.reply || "…",
            time: Date.now(),
            images: images.length ? images : undefined,
            suggestions: suggestions.length ? suggestions : undefined,
            menuRows: res.menu?.rows?.map((r) => r.title),
            openBooking: res.action === "open_booking_form" ? res.booking_form : undefined,
          },
        ]);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Something went wrong";
        setMessages((m) => [
          ...m,
          {
            role: "agent",
            text:
              msg.includes("wait a moment")
                ? "One moment please 🙏 — you're sending messages too quickly."
                : "Sorry, I couldn't reach the fleet desk just now 🙏 Please try again, or book directly on WhatsApp.",
            time: Date.now(),
          },
        ]);
      } finally {
        setPending(false);
      }
    },
    [pending]
  );

  return (
    <>
      {/* drawer */}
      <div
        className={`fixed inset-y-0 right-0 w-full sm:w-[420px] bg-zoomDark-950 border-l border-zoomBlue-500/30 shadow-2xl z-50 drawer ${open ? "open" : ""} flex flex-col`}
        role="dialog"
        aria-label="AI concierge chat"
      >
        {/* header */}
        <div className="p-4 bg-zoomDark-900 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-full bg-zoomBlue-500 text-black flex items-center justify-center font-bold text-sm shadow">
              ZR
            </div>
            <div>
              <h4 className="text-sm font-bold text-white flex items-center gap-1.5">
                Karan • ZoomRideXX Concierge
              </h4>
              <p className="text-[10px] text-slate-400">
                {config?.llm_configured === false ? "Booking assistant • basic mode" : "Instant quotes & booking • online 24/7"}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1" aria-label="Close chat">
            <Icon name="x" className="w-5 h-5" />
          </button>
        </div>

        {/* messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3 text-xs">
          {messages.map((m, i) => (
            <div key={i} className="msg-in">
              {m.role === "user" ? (
                <div className="flex justify-end">
                  <div className="bg-zoomBlue-500 text-black p-2.5 rounded-2xl rounded-tr-none font-bold max-w-[85%] whitespace-pre-wrap">
                    {m.text}
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="bg-zoomDark-900 border border-slate-800 p-3 rounded-2xl rounded-tl-none text-slate-200 leading-relaxed max-w-[92%] whitespace-pre-wrap">
                    {m.text}
                  </div>
                  {m.images?.map((img, j) => (
                    <figure key={j} className="max-w-[92%] rounded-xl overflow-hidden border border-slate-800">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={mediaUrl(img.url)}
                        alt={img.caption || "Vehicle"}
                        className="w-full h-36 object-cover"
                        loading="lazy"
                      />
                      {img.caption && (
                        <figcaption className="bg-zoomDark-900 px-3 py-1.5 text-[10px] text-slate-400">{img.caption}</figcaption>
                      )}
                    </figure>
                  ))}
                  {m.openBooking && (
                    <button
                      onClick={() => onOpenBookingForm(m.openBooking!)}
                      className="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-black font-bold text-[11px] uppercase tracking-wider transition flex items-center gap-1.5"
                    >
                      <Icon name="key" className="w-3.5 h-3.5" /> Open booking form
                    </button>
                  )}
                  {m.suggestions && m.suggestions.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 max-w-[95%]">
                      {m.suggestions.map((s) => (
                        <button
                          key={s}
                          onClick={() => send(s)}
                          className="bg-zoomDark-900 border border-slate-700 text-zoomBlue-300 px-2.5 py-1.5 rounded-full text-[11px] hover:bg-zoomBlue-500/20 transition text-left"
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {pending && (
            <div className="bg-zoomDark-900 border border-slate-800 p-3 rounded-2xl rounded-tl-none inline-flex items-center gap-1.5">
              <span className="tdot w-1.5 h-1.5 rounded-full bg-zoomBlue-400 inline-block" />
              <span className="tdot w-1.5 h-1.5 rounded-full bg-zoomBlue-400 inline-block" />
              <span className="tdot w-1.5 h-1.5 rounded-full bg-zoomBlue-400 inline-block" />
            </div>
          )}

          {messages.length <= 1 && !pending && (
            <div className="flex flex-wrap gap-1.5">
              {QUICK_CHIPS.map((chip) => (
                <button
                  key={chip}
                  onClick={() => send(chip)}
                  className="bg-zoomDark-900 border border-slate-700 text-zoomBlue-300 px-2.5 py-1.5 rounded-full text-[11px] hover:bg-zoomBlue-500/20 transition"
                >
                  {chip}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* input */}
        <form
          onSubmit={(e) => { e.preventDefault(); send(input); }}
          className="p-3 bg-zoomDark-900 border-t border-slate-800 flex gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about availability, rates, deposit…"
            aria-label="Message the concierge"
            maxLength={500}
            className="flex-1 bg-black border border-slate-700 focus:border-zoomBlue-400 rounded-full px-4 py-2 text-xs text-white outline-none"
          />
          <button
            type="submit"
            disabled={pending || !input.trim()}
            className="w-9 h-9 bg-zoomBlue-500 text-black rounded-full flex items-center justify-center disabled:opacity-40 transition"
            aria-label="Send"
          >
            <Icon name="send" className="w-4 h-4" />
          </button>
        </form>
        <div className="px-3 pb-3 bg-zoomDark-900">
          <a
            href={`https://wa.me/${waNumber(config)}?text=${encodeURIComponent("Hi ZoomRideXX!")}`}
            target="_blank"
            rel="noreferrer"
            className="block text-center text-[10px] text-emerald-400 hover:text-emerald-300 py-1.5"
          >
            Prefer WhatsApp? Continue on WhatsApp →
          </a>
        </div>
      </div>
    </>
  );
}
