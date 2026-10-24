"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { say } from "@/components/flash";
import { EmptyState, GhostButton, Section } from "@/components/ui";

interface MediaImage {
  id: string;
  filename: string;
  label: string;
  source: string;
  size: number;
  mime: string;
  url: string;
}

interface MediaResponse {
  images: MediaImage[];
  media_base_url: string;
  publicly_reachable: boolean;
  supported_formats: string[];
}

/**
 * Images the agent can actually send.
 *
 * Two sources, both portable and inside the app's own data folders — never an
 * absolute path from someone's machine:
 *   assets  → backend/assets/images (shipped with the code)
 *   uploads → uploaded here, stored under the app data directory
 * The backend addresses them by id; WhatsApp receives the real attachment (a
 * direct media upload when MEDIA_PUBLIC_BASE_URL isn't internet-reachable).
 */
export default function MediaPanel() {
  const [data, setData] = useState<MediaResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(() => {
    api<MediaResponse>("/api/media")
      .then(setData)
      .catch(() => say(false, "Cannot reach the backend for the image library."));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const upload = async (file: File) => {
    if (busy) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api<{ image: MediaImage }>("/api/media/upload", {
        method: "POST",
        body: fd,
      });
      say(true, `“${res.image.filename}” is ready — the agent can send it by asking "send the ${res.image.label}".`);
      load();
    } catch (e) {
      say(false, `Upload rejected: ${(e as Error).message}`);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async (img: MediaImage) => {
    if (!window.confirm(`Delete “${img.filename}”? The agent will no longer be able to send it.`)) return;
    try {
      await api(`/api/media/${img.id}`, { method: "DELETE" });
      say(true, "Image deleted.");
      load();
    } catch (e) {
      say(false, `Delete failed: ${(e as Error).message}`);
    }
  };

  const copy = async (img: MediaImage) => {
    try {
      await navigator.clipboard.writeText(img.url);
      setCopied(img.id);
      setTimeout(() => setCopied(""), 1500);
    } catch {
      say(false, "Clipboard unavailable — select the URL manually.");
    }
  };

  const kb = (n: number) => `${Math.max(1, Math.round(n / 1024))} KB`;

  return (
    <div className="space-y-4">
      <Section
        title="Image library"
        subtitle="Pictures the agent can send when a customer asks for one — vehicle photos above all. Files live inside the project (assets/images) or in the app's data directory after an upload; add them here instead of telling the agent about local file paths, which cannot be delivered."
        right={
          <div className="flex items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              className="btn-primary rounded-full px-4 py-2 text-[12.5px] font-semibold disabled:opacity-50"
            >
              {busy ? "Uploading…" : "＋ Attach image"}
            </button>
          </div>
        }
      >
        <div className="mb-4 flex flex-wrap items-center gap-2 text-[11.5px]">
          <span
            className={`mono inline-flex items-center gap-2 rounded-full border px-3 py-1.5 ${
              data?.publicly_reachable
                ? "border-[var(--green)]/40 bg-[var(--green)]/10 text-[var(--green)]"
                : "border-[#c9a961]/40 bg-[#c9a961]/10 text-[#c9a961]"
            }`}
          >
            {data?.publicly_reachable
              ? "DELIVERY · PUBLIC LINK"
              : "DELIVERY · DIRECT MEDIA UPLOAD"}
          </span>
          <span className="mono text-[var(--dim)]">
            {data?.media_base_url || "…"} · {data?.images.length ?? 0} image
            {(data?.images.length ?? 0) === 1 ? "" : "s"} ·{" "}
            {(data?.supported_formats || ["png", "jpg", "webp"]).join(" / ").toUpperCase()}
          </span>
        </div>
        {!data?.publicly_reachable && (
          <p className="mb-4 rounded-xl border border-white/10 bg-[var(--ink)] px-4 py-3 text-[12.5px] leading-relaxed text-[var(--muted)]">
            The media address is local ({data?.media_base_url || "http://localhost:8022"}), so
            WhatsApp cannot fetch image links from it. Locally stored pictures are therefore
            uploaded to WhatsApp directly by media id. Set <span className="mono">MEDIA_PUBLIC_BASE_URL</span>{" "}
            to your public host (tunnel or deployed proxy) to switch to public links.
          </p>
        )}

        {data && data.images.length === 0 ? (
          <EmptyState
            icon="🖼️"
            title="No images yet."
            hint="Attach a PNG, JPG or WEBP here — the agent will send it as a real WhatsApp image whenever a customer asks for it."
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(data?.images || []).map((img) => (
              <div
                key={img.id}
                className="overflow-hidden rounded-2xl border border-white/10 bg-[var(--ink)]"
              >
                <div className="grid h-40 place-items-center bg-black/30 p-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={img.url}
                    alt={img.label}
                    className="max-h-full max-w-full rounded-lg object-contain"
                  />
                </div>
                <div className="space-y-1.5 p-3">
                  <div className="flex items-center gap-2">
                    <span className="mono truncate text-[11px] text-[var(--ivory)]">{img.id}</span>
                    <span className="mono ml-auto rounded-full border border-white/10 px-2 py-0.5 text-[9.5px] text-[var(--dim)]">
                      {img.source}
                    </span>
                  </div>
                  <div className="text-[12.5px] text-[var(--ivory)]/80">{img.label}</div>
                  <div className="mono text-[10px] text-[var(--dim)]">
                    {img.mime} · {kb(img.size)}
                  </div>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    <GhostButton className="!px-2 !py-1 text-[11px]" onClick={() => copy(img)}>
                      {copied === img.id ? "Copied ✓" : "Copy URL"}
                    </GhostButton>
                    {img.source === "uploads" && (
                      <GhostButton className="!px-2 !py-1 text-[11px]" onClick={() => remove(img)}>
                        Delete
                      </GhostButton>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section
        title="How a customer gets a picture"
        subtitle="Ask in any supported language — the agent resolves the request to a product or registry id, validates the file, and hands the actual image to WhatsApp."
      >
        <ul className="space-y-2 text-[12.5px] leading-relaxed text-[var(--muted)]">
          <li>
            <span className="mono text-[var(--ivory)]">English</span> — “send me the Swift Dzire picture”
          </li>
          <li>
            <span className="mono text-[var(--ivory)]">हिंदी</span> — “मुझे स्विफ्ट डिजायर की फोटो भेजो”
          </li>
          <li>
            <span className="mono text-[var(--ivory)]">తెలుగు</span> — “స్విఫ్ట్ ఫోటో పంపండి”
          </li>
          <li className="text-[var(--dim)]">
            A request that matches several products triggers a “which one?” question in the active
            language instead of a guess — the caption always follows the conversation language.
          </li>
        </ul>
      </Section>
    </div>
  );
}
