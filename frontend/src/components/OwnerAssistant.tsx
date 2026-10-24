"use client";

import React, { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { MicButton } from "@/components/sara";

interface Msg { role: "you" | "agent"; content: string }

export default function OwnerAssistant() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "agent",
      content:
        "Owner console ready. Ask me anything about your WhatsApp agent — who has messaged, what I know about customers, what's in the catalogue, which orders are confirmed, or what's loaded in the knowledge base.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const send = async (raw?: string) => {
    const text = (raw ?? input).trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "you", content: text }]);
    setBusy(true);
    try {
      const data = await api<{ reply: string; error?: string }>("/api/owner", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      setMessages((m) => [
        ...m,
        { role: "agent", content: data.error ? `⚠ ${data.error}` : data.reply },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "agent", content: "⚠ Cannot reach the backend — is it running on port 8022?" },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const suggestions = [
    "Who has messaged recently?",
    "What's in the catalogue?",
    "Which orders are active?",
    "What knowledge is loaded?",
  ];

  return (
    <div className="mx-auto max-w-3xl">
      <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0b0d10]">
        <div className="flex items-center gap-2.5 border-b border-white/5 bg-[var(--ink-2)] px-5 py-3.5">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-[var(--brass)]/15 text-[13px]">🛠️</span>
          <div className="leading-tight">
            <div className="text-[13.5px] font-medium">Owner assistant</div>
            <div className="mono text-[10.5px] text-[var(--dim)]">POST /api/owner · answers from live business data only</div>
          </div>
        </div>
        <div ref={scrollRef} className="h-[380px] space-y-3 overflow-y-auto px-5 py-4">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "you" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[85%] whitespace-pre-line rounded-2xl px-4 py-2.5 text-[13.5px] leading-relaxed ${
                  m.role === "you"
                    ? "rounded-br-sm bg-[var(--green)] text-[#06130c]"
                    : "rounded-bl-sm border border-white/10 bg-[var(--ink-2)] text-[#e9edef]"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex items-center gap-1 px-1" aria-label="Assistant is typing">
              <span className="dot h-1.5 w-1.5 rounded-full bg-[#8696a0]" />
              <span className="dot h-1.5 w-1.5 rounded-full bg-[#8696a0]" />
              <span className="dot h-1.5 w-1.5 rounded-full bg-[#8696a0]" />
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2 border-t border-white/5 px-5 py-3">
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              disabled={busy}
              className="rounded-full border border-white/10 px-3 py-1.5 text-[12px] text-[var(--muted)] transition-colors hover:border-white/25 hover:text-[var(--ivory)] disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 border-t border-white/5 bg-[var(--ink-2)] px-5 py-3.5">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Ask as the business owner…"
            aria-label="Owner message"
            className="flex-1 rounded-full border border-white/10 bg-[#0a0c10] px-4 py-2.5 text-[13px] text-[#e9edef] placeholder-[#6b727d] focus:border-[var(--green)]/50 focus:outline-none"
          />
          <MicButton onResult={(t) => send(t)} busy={busy} />
          <button
            onClick={() => send()}
            disabled={busy}
            aria-label="Send"
            className="btn-primary grid h-9 w-9 shrink-0 place-items-center rounded-full transition-opacity disabled:opacity-50"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M3 11l18-8-8 18-2-8-8-2z" /></svg>
          </button>
        </div>
      </div>
    </div>
  );
}
