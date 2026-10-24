"use client";

import React, { useEffect, useRef, useState, type ReactNode } from "react";

export const Container = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`mx-auto w-full max-w-[1200px] px-5 sm:px-8 ${className}`}>{children}</div>
);

export const Eyebrow = ({ children }: { children: ReactNode }) => (
  <span className="mono inline-flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-[var(--green)]">
    <span className="h-1 w-1 rounded-full bg-[var(--green)]" aria-hidden />
    {children}
  </span>
);

export const SectionHead = ({
  eyebrow,
  title,
  body,
  align = "left",
}: {
  eyebrow: string;
  title: ReactNode;
  body?: string;
  align?: "left" | "center";
}) => (
  <div className={`max-w-2xl ${align === "center" ? "mx-auto text-center" : ""}`} data-reveal>
    <Eyebrow>{eyebrow}</Eyebrow>
    <h2 className="serif mt-4 text-[2.1rem] leading-[1.05] sm:text-[2.75rem]">{title}</h2>
    {body && <p className="mt-4 text-[15.5px] leading-relaxed text-[var(--muted)]">{body}</p>}
  </div>
);

export function useReveal() {
  useEffect(() => {
    const els = Array.from(
      document.querySelectorAll<HTMLElement>(".sara [data-reveal]"),
    );
    const reveal = (el: HTMLElement) => {
      const delay = Number(el.dataset.delay ?? 0);
      el.style.transitionDelay = `${delay}ms`;
      el.classList.add("is-visible");
    };
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            reveal(e.target as HTMLElement);
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" },
    );
    // Reveal everything already inside the viewport immediately — an
    // IntersectionObserver never fires in a tab that isn't rendering
    // (background window), which left the whole console blank.
    const viewport = window.innerHeight || 800;
    els.forEach((el) => {
      const box = el.getBoundingClientRect();
      if (box.top < viewport && box.bottom > 0) reveal(el);
      else io.observe(el);
    });
    // Failsafe: content must never stay invisible, even if the observer
    // never delivers an intersection (hidden panes, suspended tabs).
    const failsafe = window.setTimeout(() => {
      els.forEach((el) => {
        if (!el.classList.contains("is-visible")) {
          reveal(el);
          io.unobserve(el);
        }
      });
    }, 1200);
    return () => {
      window.clearTimeout(failsafe);
      io.disconnect();
    };
  }, []);
}

/* -------------------------------------------------------------------------- */
/* Nav — same shape as SARA's fixed top nav                                    */
/* -------------------------------------------------------------------------- */
export function Nav({ links, subtitle }: { links: [string, string][]; subtitle: string }) {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background,border-color,backdrop-filter] duration-300 ${
        scrolled ? "border-b border-white/5 bg-[#0d1117]/85 backdrop-blur-md" : "border-b border-transparent"
      }`}
    >
      <Container className="flex h-16 items-center justify-between">
        <span className="flex items-center gap-2.5">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-[var(--brass)] text-[13px] font-semibold text-[var(--ink)]">Z</span>
          <span className="text-[15px] font-medium tracking-tight">ZOOMRIDEXX CAR RENTALS</span>
          <span className="hidden text-[13px] text-[var(--dim)] sm:inline">{subtitle}</span>
        </span>
        <nav className="hidden items-center gap-7 md:flex" aria-label="Primary">
          {links.map(([l, h]) => (
            <a key={h} href={h} className="text-[13.5px] text-[var(--muted)] transition-colors hover:text-[var(--ivory)]">
              {l}
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-3 md:flex">
          <a href="#console" className="btn-primary rounded-full px-4 py-2 text-[13.5px] font-semibold">
            Open console
          </a>
        </div>
        <button
          className="grid h-9 w-9 place-items-center rounded-md border border-white/10 md:hidden"
          aria-expanded={open}
          aria-label="Toggle menu"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="relative block h-[10px] w-4">
            <span className={`absolute left-0 top-0 h-[1.5px] w-4 bg-current transition-transform ${open ? "translate-y-[4.5px] rotate-45" : ""}`} />
            <span className={`absolute bottom-0 left-0 h-[1.5px] w-4 bg-current transition-transform ${open ? "-translate-y-[4.5px] -rotate-45" : ""}`} />
          </span>
        </button>
      </Container>
      {open && (
        <div className="border-t border-white/5 bg-[#0d1117] md:hidden">
          <Container className="flex flex-col gap-1 py-3">
            {links.map(([l, h]) => (
              <a key={h} href={h} onClick={() => setOpen(false)} className="rounded-md px-2 py-2.5 text-[15px] text-[var(--muted)] hover:bg-white/5 hover:text-[var(--ivory)]">
                {l}
              </a>
            ))}
            <a href="#console" onClick={() => setOpen(false)} className="btn-primary mt-2 rounded-full px-4 py-2.5 text-center text-[14px] font-semibold">
              Open console
            </a>
          </Container>
        </div>
      )}
    </header>
  );
}

/* -------------------------------------------------------------------------- */
/* MicButton — browser SpeechRecognition (SARA's exact implementation)          */
/* -------------------------------------------------------------------------- */
type SpeechRecogEvent = { results: ArrayLike<ArrayLike<{ transcript: string }>> };
type SpeechRecog = {
  lang: string; continuous: boolean; interimResults: boolean;
  onstart: (() => void) | null; onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onresult: ((e: SpeechRecogEvent) => void) | null;
  start: () => void; stop: () => void;
};
type SpeechWindow = {
  SpeechRecognition?: new () => SpeechRecog;
  webkitSpeechRecognition?: new () => SpeechRecog;
};

/**
 * Voice input. `lang` is a BCP-47 tag so dictation follows the active
 * conversation language (hi-IN / te-IN / en-IN). Browser support for a given
 * language varies; an unsupported one surfaces the browser's own error rather
 * than silently transcribing in another language.
 */
export function MicButton({
  onResult,
  busy,
  lang = "en-IN",
}: {
  onResult: (text: string) => void;
  busy: boolean;
  lang?: string;
}) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecog | null>(null);
  useEffect(() => () => { recRef.current?.stop(); }, []);

  const toggle = () => {
    if (busy) return;
    if (listening) { recRef.current?.stop(); return; }
    const w = window as unknown as SpeechWindow;
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Ctor) {
      alert("Voice input isn't supported in this browser. Use Chrome or Edge.");
      return;
    }
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = false;
    rec.interimResults = false;
    rec.onstart = () => setListening(true);
    rec.onend = () => { setListening(false); recRef.current = null; };
    rec.onerror = (e) => {
      setListening(false); recRef.current = null;
      if (e.error && e.error !== "aborted" && e.error !== "no-speech") {
        alert(`Microphone error: ${e.error}. Please try again.`);
      }
    };
    rec.onresult = (e) => {
      const text = e.results?.[0]?.[0]?.transcript?.trim();
      if (text) onResult(text);
    };
    recRef.current = rec;
    rec.start();
  };

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      aria-label={listening ? "Stop listening" : "Voice input"}
      title={listening ? "Listening… click to stop" : "Speak instead of typing"}
      className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border transition-colors ${
        listening
          ? "animate-pulse border-red-400/60 bg-red-500/20 text-red-300"
          : "border-white/10 bg-[#1f2c34] text-[#8696a0] hover:border-white/25 hover:text-[#e9edef]"
      }`}
    >
      {listening ? (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <rect x="6" y="6" width="12" height="12" rx="2" />
        </svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" x2="12" y1="19" y2="22" />
        </svg>
      )}
    </button>
  );
}
