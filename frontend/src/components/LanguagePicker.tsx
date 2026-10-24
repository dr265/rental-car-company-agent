"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * Language selector for the console.
 *
 * The list is NOT hard-coded here: it is fetched from /api/languages, which
 * reads the single backend registry (app/languages.py). Adding a language on
 * the backend therefore makes it appear here — English and Hindi/Hinglish
 * today — without touching the UI.
 */
export interface LanguageOption {
  code: string;
  label: string;
  native: string;
  flag: string;
}

/** BCP-47 tag for browser features (voice input) per agent language code. */
export const LANGUAGE_BCP47: Record<string, string> = {
  en: "en-IN",
  hi: "hi-IN",
};

export function useLanguages() {
  const [languages, setLanguages] = useState<LanguageOption[]>([]);
  useEffect(() => {
    api<{ languages: LanguageOption[] }>("/api/languages")
      .then((d) => setLanguages(d.languages || []))
      .catch(() => setLanguages([]));
  }, []);
  return languages;
}

export default function LanguagePicker({
  value,
  onChange,
  busy,
  compact = false,
  label = "Language",
}: {
  value: string;
  onChange: (code: string) => void;
  busy?: boolean;
  compact?: boolean;
  label?: string;
}) {
  const languages = useLanguages();
  if (languages.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={label}>
      {!compact && (
        <span className="mono mr-0.5 text-[10px] uppercase tracking-[0.14em] text-[var(--dim)]">
          {label}
        </span>
      )}
      {languages.map((l) => {
        const active = l.code === value;
        return (
          <button
            key={l.code}
            type="button"
            onClick={() => onChange(l.code)}
            disabled={busy}
            aria-pressed={active}
            title={`${l.label}${active ? " · active" : ""}`}
            className={`rounded-full border px-2.5 py-1 text-[11.5px] transition-colors disabled:opacity-50 ${
              active
                ? "border-[var(--green)]/50 bg-[var(--green)]/15 font-semibold text-[var(--green)]"
                : "border-white/10 text-[var(--muted)] hover:border-white/25 hover:text-[var(--ivory)]"
            }`}
          >
            {l.flag ? `${l.flag} ` : ""}
            {l.native || l.label}
          </button>
        );
      })}
    </div>
  );
}
