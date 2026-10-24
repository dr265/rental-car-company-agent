"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { EmptyState, GhostButton, PrimaryButton, Section, TextInput } from "@/components/ui";
import { say } from "@/components/flash";

interface Doc {
  id: string;
  filename: string;
  size: number;
  status: "uploading" | "processing" | "ready" | "failed" | string;
  error: string;
  chunk_count: number;
  created_at: string | null;
}

interface Hit {
  filename: string;
  score: number;
  text: string;
}

export default function KnowledgePanel() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Hit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const loadDocs = useCallback(() => {
    api<{ documents: Doc[] }>("/api/knowledge/documents")
      .then((d) => setDocs(d.documents))
      .catch((e: Error) => say(false, `Cannot load documents: ${e.message}`));
  }, []);

  useEffect(() => {
    loadDocs();
    const t = setInterval(loadDocs, 6000);
    return () => clearInterval(t);
  }, [loadDocs]);

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await api<{ status: string; filename: string; chunks: number }>(
        "/api/knowledge/upload",
        { method: "POST", body: form }
      );
      say(true, `“${res.filename}” indexed — ${res.chunks} chunks ready for retrieval.`);
      loadDocs();
    } catch (e) {
      say(false, `Upload failed: ${(e as Error).message}`);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const doSearch = async () => {
    if (!q.trim()) return;
    setSearching(true);
    try {
      const d = await api<{ results: Hit[] }>(`/api/knowledge/search?q=${encodeURIComponent(q.trim())}`);
      setResults(d.results);
    } catch (e) {
      say(false, `Search failed: ${(e as Error).message}`);
    } finally {
      setSearching(false);
    }
  };

  const remove = async (doc: Doc) => {
    if (!window.confirm(`Remove “${doc.filename}” from the knowledge base?`)) return;
    try {
      await api(`/api/knowledge/documents/${doc.id}`, { method: "DELETE" });
      say(true, `Removed “${doc.filename}”.`);
      loadDocs();
    } catch (e) {
      say(false, `Delete failed: ${(e as Error).message}`);
    }
  };

  const statusChip = (d: Doc) => {
    const map: Record<string, string> = {
      ready: "border-jewel/40 bg-jewel/10 text-jewel",
      processing: "border-brass/40 bg-brass/10 text-brass",
      uploading: "border-brass/40 bg-brass/10 text-brass",
      failed: "border-red-500/40 bg-red-500/10 text-red-300",
    };
    return map[d.status] || "border-white/15 text-white/50";
  };

  return (
    <div className="space-y-5">
      <Section
        title="Upload shop knowledge"
        subtitle="Price lists, policies, FAQs, ingredients, allergen notes and festive offers — PDF, DOCX, XLSX, CSV, TXT, JSON or MD. Files are parsed and chunk-indexed server-side; the agent retrieves the matching excerpts on every customer question."
      >
        <div className="flex flex-wrap items-center gap-3">
          <label className={`inline-flex cursor-pointer items-center gap-2 rounded-xl bg-jewel px-4 py-2.5 text-[13px] font-semibold text-[#06130c] transition-opacity hover:opacity-90 ${uploading ? "opacity-50" : ""}`}>
            {uploading ? "Uploading…" : "⬆ Upload file"}
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.xlsx,.xls,.csv,.txt,.json,.md"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
              }}
            />
          </label>
          <span className="text-[12px] text-ivory/50">Max 20 MB · parsed fully server-side</span>
          <span className="text-[12px] text-ivory/50">
            · bulk product and pack editing lives in the <span className="text-brass">Products</span> tab
          </span>
        </div>

        <div className="mt-6 space-y-2">
          {docs === null && <div className="mono py-4 text-center text-[12px] text-white/40">LOADING…</div>}
          {docs?.length === 0 && (
            <EmptyState
              icon="📚"
              title="Nothing uploaded yet"
              hint="Upload your price list or policies — the agent quotes from them instead of guessing."
            />
          )}
          {docs?.map((d) => (
            <div key={d.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-white/10 bg-ink px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13.5px]">{d.filename}</div>
                <div className="mono mt-0.5 text-[10.5px] text-white/40">
                  {(d.size / 1024).toFixed(1)} KB · {d.chunk_count} chunks · {d.created_at ? new Date(d.created_at).toLocaleString() : ""}
                </div>
                {d.status === "failed" && d.error && (
                  <div className="mono mt-1 rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-[10px] text-red-300">
                    {d.error}
                  </div>
                )}
              </div>
              <span className={`mono rounded-full border px-2.5 py-1 text-[10px] uppercase ${statusChip(d)}`}>
                {d.status}
              </span>
              <GhostButton onClick={() => remove(d)} className="hover:border-red-400/40 hover:text-red-300">
                Remove
              </GhostButton>
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="Test retrieval"
        subtitle="Exactly what the agent will see: run a BM25 search over the indexed chunks."
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-[240px] flex-1">
            <TextInput value={q} onChange={setQ} onEnter={doSearch} placeholder="e.g. airport pickup fee SUV weekend rate" />
          </div>
          <PrimaryButton onClick={doSearch} disabled={searching || !q.trim()}>
            {searching ? "Searching…" : "Search"}
          </PrimaryButton>
        </div>
        {results !== null && (
          <div className="mt-4 space-y-2">
            {results.length === 0 && <p className="text-[13px] text-ivory/50">No matches.</p>}
            {results.map((r, i) => (
              <div key={i} className="rounded-xl border border-white/10 bg-ink p-3">
                <div className="mono text-[10px] text-white/40">{r.filename} · score {r.score}</div>
                <div className="mt-1 whitespace-pre-line text-[12.5px] text-ivory/80">{r.text}</div>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
