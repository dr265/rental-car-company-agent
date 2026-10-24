"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { EmptyState, GhostButton, PrimaryButton, Section, TextInput } from "@/components/ui";
import { say } from "@/components/flash";

interface Vehicle {
  code: string;
  name: string;
  category: string | null;
  transmission: string | null;
  fuel: string | null;
  seats: number | null;
  price_per_day: number | null;
  price_per_hour: number | null;
  deposit: number | null;
  driver_fee_per_day: number | null;
  mileage_limit_per_day: number | null;
  extra_km_charge: number | null;
  available: number | boolean;
  image_url: string | null;
  description: string | null;
  location: string | null;
}

const EMPTY = {
  code: "", name: "", category: "", transmission: "", fuel: "", seats: "",
  price_per_day: "", deposit: "", driver_fee_per_day: "", mileage_limit_per_day: "",
  extra_km_charge: "", image_url: "", location: "", description: "", available: true,
};

type FormState = {
  [K in keyof typeof EMPTY]: (typeof EMPTY)[K];
};

/**
 * Fleet — the agent's ONLY source of truth for availability and prices.
 * Create/update is an upsert by code (exactly like the backend contract),
 * plus CSV/XLSX bulk import and delete. This panel is the only place the
 * fleet, its packages and its deposit values are maintained.
 */
export default function FleetPanel() {
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY });
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(() => {
    api<{ vehicles: Vehicle[] }>("/api/vehicles")
      .then((d) => setVehicles(d.vehicles))
      .catch((e: Error) => say(false, `Cannot load the fleet: ${e.message}`));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const set = (key: keyof FormState, value: string | boolean) =>
    // computed-key update: the key and value types are checked at each call
    // site above, so the assembled object is exactly FormState
    setForm((f) => ({ ...f, [key]: value }) as FormState);

  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  const save = async () => {
    const code = form.code.trim().toUpperCase();
    const name = form.name.trim();
    if (!code || !name) {
      say(false, "Code and name are required.");
      return;
    }
    setSaving(true);
    try {
      await api("/api/vehicles", {
        method: "POST",
        body: JSON.stringify({
          code,
          name,
          category: form.category.trim() || null,
          transmission: form.transmission.trim() || null,
          fuel: form.fuel.trim() || null,
          seats: num(form.seats),
          price_per_day: num(form.price_per_day),
          deposit: num(form.deposit),
          driver_fee_per_day: num(form.driver_fee_per_day),
          mileage_limit_per_day: num(form.mileage_limit_per_day),
          extra_km_charge: num(form.extra_km_charge),
          image_url: form.image_url.trim() || null,
          location: form.location.trim() || null,
          description: form.description.trim() || null,
          available: Boolean(form.available),
        }),
      });
      say(true, `${code} saved — the agent quotes it from the very next message.`);
      setForm({ ...EMPTY });
      setShowForm(false);
      load();
    } catch (e) {
      say(false, `Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const edit = (v: Vehicle) => {
    setForm({
      code: v.code,
      name: v.name,
      category: v.category ?? "",
      transmission: v.transmission ?? "",
      fuel: v.fuel ?? "",
      seats: v.seats == null ? "" : String(v.seats),
      price_per_day: v.price_per_day == null ? "" : String(v.price_per_day),
      deposit: v.deposit == null ? "" : String(v.deposit),
      driver_fee_per_day: v.driver_fee_per_day == null ? "" : String(v.driver_fee_per_day),
      mileage_limit_per_day: v.mileage_limit_per_day == null ? "" : String(v.mileage_limit_per_day),
      extra_km_charge: v.extra_km_charge == null ? "" : String(v.extra_km_charge),
      image_url: v.image_url ?? "",
      location: v.location ?? "",
      description: v.description ?? "",
      available: Boolean(v.available),
    });
    setShowForm(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const remove = async (code: string) => {
    if (!window.confirm(`Remove ${code} from the fleet?`)) return;
    try {
      await api(`/api/vehicles/${encodeURIComponent(code)}`, { method: "DELETE" });
      say(true, `${code} removed.`);
      load();
    } catch (e) {
      say(false, `Delete failed: ${(e as Error).message}`);
    }
  };

  const importFile = async (file: File) => {
    setImporting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api<{ saved: number; errors: string[] }>("/api/vehicles/import", {
        method: "POST",
        body: fd,
      });
      if (r.errors?.length) {
        say(false, `Imported ${r.saved} vehicles · ${r.errors.length} row error(s): ${r.errors[0]}`);
      } else {
        say(true, `Imported ${r.saved} vehicles.`);
      }
      load();
    } catch (e) {
      say(false, `Import failed: ${(e as Error).message}`);
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const textFields: [keyof FormState, string, string][] = [
    ["code", "Code *", "CAR-SWIFT-01"],
    ["name", "Name *", "Maruti Swift Dzire"],
    ["category", "Category", "hatchback"],
    ["seats", "Seats", "5"],
    ["price_per_day", "₹/day", "2500"],
    ["deposit", "Deposit", "5000"],
    ["driver_fee_per_day", "Chauffeur ₹/day", "800"],
    ["mileage_limit_per_day", "km/day", "250"],
    ["extra_km_charge", "₹/extra km", "12"],
    ["transmission", "Transmission", "manual / auto"],
    ["fuel", "Fuel", "petrol"],
    ["location", "Pickup location", "City / airport"],
    ["image_url", "Photo URL", "https://…"],
  ];

  return (
    <div className="space-y-5">
      <Section
        title="Fleet (grounding data)"
        subtitle="The agent quotes availability, prices, deposits and mileage ONLY from these real rows. An empty fleet means the agent says the team will confirm — never a made-up price."
        right={
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.xlsm"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importFile(f);
              }}
            />
            <GhostButton onClick={() => fileRef.current?.click()} disabled={importing}>
              {importing ? "Importing…" : "⇩ Import CSV/XLSX"}
            </GhostButton>
            <PrimaryButton onClick={() => setShowForm((v) => !v)}>
              {showForm ? "✕ Close" : "＋ Add vehicle"}
            </PrimaryButton>
          </div>
        }
      >
        {showForm && (
          <div className="mb-5 rounded-xl border border-white/10 bg-ink p-4">
            <div className="mono mb-3 text-[11px] uppercase tracking-[0.16em] text-[var(--dim)]">
              Add / update vehicle — save is an upsert by code
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {textFields.map(([key, label, ph]) => (
                <label key={key} className="text-[12px]">
                  <span className="mb-1 block text-ivory/60">{label}</span>
                  <TextInput
                    value={String(form[key])}
                    onChange={(v) => set(key, v)}
                    placeholder={ph}
                    type={["seats", "price_per_day", "deposit", "driver_fee_per_day", "mileage_limit_per_day", "extra_km_charge"].includes(key) ? "number" : "text"}
                  />
                </label>
              ))}
              <label className="text-[12px]">
                <span className="mb-1 block text-ivory/60">State</span>
                <button
                  type="button"
                  onClick={() => set("available", !form.available)}
                  className={`w-full rounded-xl border px-3.5 py-2.5 text-left text-[13px] transition-colors ${
                    form.available
                      ? "border-jewel/40 bg-jewel/10 text-jewel"
                      : "border-white/15 bg-ink text-white/50"
                  }`}
                >
                  {form.available ? "✓ available for booking" : "○ parked / withdrawn"}
                </button>
              </label>
              <label className="text-[12px] sm:col-span-3">
                <span className="mb-1 block text-ivory/60">Description</span>
                <textarea
                  value={form.description}
                  onChange={(e) => set("description", e.target.value)}
                  rows={2}
                  placeholder="Boot space, luggage, fuel efficiency, condition…"
                  className="w-full rounded-xl border border-white/10 bg-ink px-3.5 py-2.5 text-[13px] outline-none focus:border-jewel/60"
                />
              </label>
            </div>
            <div className="mt-3 flex gap-3">
              <PrimaryButton onClick={save} disabled={saving || !form.code.trim() || !form.name.trim()}>
                {saving ? "Saving…" : "Save vehicle"}
              </PrimaryButton>
              <GhostButton
                onClick={() => { setForm({ ...EMPTY }); setShowForm(false); }}
              >
                Cancel
              </GhostButton>
            </div>
          </div>
        )}

        {vehicles === null && <div className="mono py-4 text-center text-[12px] text-white/40">LOADING…</div>}
        {vehicles?.length === 0 && (
          <EmptyState
            icon="🚗"
            title="No vehicles in the fleet yet"
            hint="Add vehicles one by one or upload a CSV/XLSX catalogue (columns: code, name, category, seats, price_per_day, deposit, …)."
          />
        )}
        {vehicles && vehicles.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead>
                <tr className="mono border-b border-white/10 text-[10px] uppercase tracking-wider text-white/40">
                  <th className="py-2 pr-3">Code</th>
                  <th className="py-2 pr-3">Name</th>
                  <th className="py-2 pr-3">Category</th>
                  <th className="py-2 pr-3">Seats</th>
                  <th className="py-2 pr-3">₹/day</th>
                  <th className="py-2 pr-3">Deposit</th>
                  <th className="py-2 pr-3">km/day</th>
                  <th className="py-2 pr-3">State</th>
                  <th className="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {vehicles.map((v) => (
                  <tr key={v.code} className="border-b border-white/5">
                    <td className="mono py-2.5 pr-3 text-brass">{v.code}</td>
                    <td className="py-2.5 pr-3">{v.name}</td>
                    <td className="py-2.5 pr-3 text-ivory/60">{v.category || "—"}</td>
                    <td className="py-2.5 pr-3 text-ivory/60">{v.seats ?? "—"}</td>
                    <td className="py-2.5 pr-3">
                      {v.price_per_day != null ? `₹${v.price_per_day.toLocaleString("en-IN")}` : "—"}
                    </td>
                    <td className="py-2.5 pr-3 text-ivory/60">
                      {v.deposit != null ? `₹${v.deposit.toLocaleString("en-IN")}` : "—"}
                    </td>
                    <td className="py-2.5 pr-3 text-ivory/60">{v.mileage_limit_per_day ?? "—"}</td>
                    <td className="py-2.5 pr-3">
                      {v.available ? (
                        <span className="mono rounded-full border border-jewel/40 bg-jewel/10 px-2 py-0.5 text-[10px] text-jewel">
                          available
                        </span>
                      ) : (
                        <span className="mono rounded-full border border-white/15 px-2 py-0.5 text-[10px] text-white/50">
                          parked
                        </span>
                      )}
                    </td>
                    <td className="py-2.5">
                      <div className="flex justify-end gap-1.5">
                        <GhostButton onClick={() => edit(v)} className="!px-2 !py-1" title="Load into the form">
                          ✎
                        </GhostButton>
                        <GhostButton
                          onClick={() => remove(v.code)}
                          className="!px-2 !py-1 hover:border-red-400/40 hover:text-red-300"
                          title="Delete vehicle"
                        >
                          ✕
                        </GhostButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
