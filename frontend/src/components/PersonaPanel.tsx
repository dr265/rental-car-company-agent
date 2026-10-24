"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PrimaryButton, Section } from "@/components/ui";
import { say } from "@/components/flash";

interface PersonaField {
  label: string;
  value: string;
  is_default: boolean;
}

export default function PersonaPanel() {
  const [fields, setFields] = useState<Record<string, PersonaField> | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api<{ fields: Record<string, PersonaField>; core_persona_locked: boolean }>("/api/persona")
      .then((d) => {
        setFields(d.fields);
        const init: Record<string, string> = {};
        for (const [k, v] of Object.entries(d.fields)) init[k] = v.value;
        setDraft(init);
      })
      .catch((e: Error) => say(false, `Cannot load persona: ${e.message}`));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const changed: Record<string, string> = {};
      for (const [k, v] of Object.entries(draft)) {
        if (fields && v !== fields[k]?.value) changed[k] = v;
        if (fields && !fields[k]?.is_default && v === fields[k]?.value) changed[k] = v; // keep persisted value
      }
      await api("/api/persona", { method: "PUT", body: JSON.stringify({ updates: changed }) });
      say(true, "Persona saved — the agent uses it from the very next message.");
      load();
    } catch (e) {
      say(false, `Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  if (!fields) {
    return <div className="mono py-6 text-center text-[12px] text-white/40">LOADING PERSONA…</div>;
  }

  return (
    <Section
      title="Business persona"
      subtitle="What the car-rental business is and how the agent speaks. Saved to the backend and injected into every conversation."
    >
      <div className="mb-4 rounded-xl border border-brass/30 bg-brass/5 px-4 py-3 text-[12.5px] text-brass">
        🔒 The car-rental core role is locked — persona edits customise the business, they can never turn
        the agent into a generic assistant.
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {Object.entries(fields).map(([key, f]) => (
          <label key={key} className={key === "business_description" ? "sm:col-span-2" : ""}>
            <span className="mb-1.5 flex items-baseline gap-2 text-[12.5px] text-ivory/70">
              {f.label}
              {f.is_default && <span className="mono text-[9.5px] uppercase text-white/30">default</span>}
            </span>
            {key === "business_description" ||
            key === "service_policies" ||
            key === "return_policy" ||
            key === "delivery_policy" ||
            key === "customization_policy" ? (
              <textarea
                value={draft[key] ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                rows={2}
                className="w-full rounded-xl border border-white/10 bg-ink px-3.5 py-2.5 text-[13px] text-ivory placeholder:text-white/30 outline-none focus:border-jewel/60"
              />
            ) : (
              <input
                value={draft[key] ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                className="w-full rounded-xl border border-white/10 bg-ink px-3.5 py-2.5 text-[13px] text-ivory placeholder:text-white/30 outline-none focus:border-jewel/60"
              />
            )}
          </label>
        ))}
      </div>
      <div className="mt-5">
        <PrimaryButton onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save persona"}
        </PrimaryButton>
      </div>
    </Section>
  );
}
