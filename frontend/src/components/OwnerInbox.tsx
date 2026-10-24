"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { MicButton } from "@/components/sara";
import LanguagePicker, { LANGUAGE_BCP47 } from "@/components/LanguagePicker";
import { say } from "@/components/flash";
import ImageAlbum from "@/components/ImageAlbum";

interface Conversation {
  id: string;
  customer_name: string;
  display_phone: string;
  status: string;
  paused_at: string | null;
  language: string;
  language_source: string;
  unread_count: number;
  summary: string;
  last_message_at: string | null;
  last_message_preview: string;
}

interface Msg {
  id: string;
  direction: "in" | "out" | string;
  sender: string;
  body: string;
  msg_type: string;
  image_url: string;
  status: string;
  intent: string;
  error: string;
  created_at: string;
}

interface AttachedImage {
  id: string;
  filename: string;
  label: string;
  url: string;
}

interface Detail {
  conversation: Conversation;
  customer: { display_phone: string; whatsapp_name: string; first_seen_at: string | null; notes: string } | null;
  memory: { key: string; value: string; source: string; updated_at: string | null }[];
  messages: Msg[];
}

type ThreadItem =
  | { kind: "msg"; msg: Msg }
  | {
      kind: "album";
      id: string;
      direction: string;
      sender: string;
      status: string;
      intent: string;
      created_at: string;
      images: { id: string; url: string; caption: string; label: string }[];
    };

/** Consecutive image bubbles from the same sender become one swipeable album —
 *  that is how the 17-car gallery is actually delivered (no native WA album). */
function groupThread(messages: Msg[]): ThreadItem[] {
  const items: ThreadItem[] = [];
  for (const m of messages) {
    const isImage = m.msg_type === "image" && Boolean(m.image_url);
    if (!isImage) {
      items.push({ kind: "msg", msg: m });
      continue;
    }
    const last = items[items.length - 1];
    if (last && last.kind === "album"
        && last.direction === m.direction && last.sender === m.sender) {
      last.images.push({
        id: m.id, url: m.image_url, caption: m.body || "", label: m.body || "",
      });
      continue;
    }
    items.push({
      kind: "album",
      id: m.id,
      direction: m.direction,
      sender: m.sender,
      status: m.status,
      intent: m.intent,
      created_at: m.created_at,
      images: [{ id: m.id, url: m.image_url, caption: m.body || "", label: m.body || "" }],
    });
  }
  return items;
}

export default function OwnerInbox() {
  const [convs, setConvs] = useState<Conversation[] | null>(null);
  const [autoResumeMin, setAutoResumeMin] = useState(0);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [attached, setAttached] = useState<AttachedImage | null>(null);
  const [langBusy, setLangBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const thread = useMemo(() => groupThread(detail?.messages ?? []), [detail?.messages]);

  const loadList = useCallback(() => {
    api<{ conversations: Conversation[]; auto_resume_minutes: number }>(
      `/api/conversations${search.trim() ? `?q=${encodeURIComponent(search.trim())}` : ""}`
    )
      .then((d) => {
        setConvs(d.conversations);
        setAutoResumeMin(d.auto_resume_minutes ?? 0);
      })
      .catch(() => say(false, "Cannot react the backend for conversations."));
  }, [search]);

  const loadDetail = useCallback((id: string) => {
    api<Detail>(`/api/conversations/${id}`)
      .then((d) => {
        setDetail(d);
        api(`/api/conversations/${id}/read`, { method: "POST" }).catch(() => {});
      })
      .catch(() => say(false, "Cannot load the conversation."));
  }, []);

  useEffect(() => {
    loadList();
    const h = setInterval(loadList, 5000);
    return () => clearInterval(h);
  }, [loadList]);

  useEffect(() => {
    if (!selected) return;
    loadDetail(selected);
    const h = setInterval(() => loadDetail(selected), 4000);
    return () => clearInterval(h);
  }, [selected, loadDetail]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [detail?.messages.length, selected]);

  // Attach a real image to a staff reply: the file is uploaded to the media
  // library first and then sent as an actual WhatsApp image by its id — the
  // endpoint refuses anything that is not a stored image.
  const attachFile = async (file: File) => {
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api<{ image: AttachedImage }>("/api/media/upload", {
        method: "POST",
        body: fd,
      });
      setAttached(res.image);
      say(true, `“${res.image.label || res.image.filename}” attached — it goes out with your reply.`);
    } catch (e) {
      say(false, `Attachment rejected: ${(e as Error).message}`);
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const sendReply = async () => {
    const text = reply.trim();
    if (!text || !selected || sending) return;
    setSending(true);
    const media = attached;
    setReply("");
    setAttached(null);
    try {
      const res = await api<{ status: string; error: string }>(
        `/api/conversations/${selected}/reply`,
        { method: "POST", body: JSON.stringify({ text, media_id: media?.id || "" }) }
      );
      if (res.status === "sent") {
        say(true, media
          ? "Reply + image sent via WhatsApp — the agent is paused for this chat."
          : "Reply sent via WhatsApp — the agent is paused for this chat.");
      } else {
        say(false, `WhatsApp rejected the send: ${res.error || "unknown error"}`);
      }
      loadDetail(selected);
      loadList();
    } catch (e) {
      say(false, `Send failed: ${(e as Error).message}`);
    } finally {
      setSending(false);
    }
  };

  const resumeAgent = async () => {
    if (!selected) return;
    try {
      await api(`/api/conversations/${selected}/resume`, { method: "POST" });
      say(true, "Agent resumed for this conversation.");
      loadDetail(selected);
      loadList();
    } catch (e) {
      say(false, `Resume failed: ${(e as Error).message}`);
    }
  };

  // Bulk un-stick: hand every paused chat back to the agent in one click.
  const resumeAll = async () => {
    if (!window.confirm("Give every 'WITH STAFF' conversation back to the AI agent?")) return;
    try {
      const res = await api<{ resumed: number }>("/api/conversations/resume-all", { method: "POST" });
      say(true, `${res.resumed} conversation(s) resumed — the agent is answering again.`);
      loadList();
      if (selected) loadDetail(selected);
    } catch (e) {
      say(false, `Resume all failed: ${(e as Error).message}`);
    }
  };

  const resetConversation = async () => {
    if (!selected) return;
    if (!window.confirm(
      "Reset this conversation?\n\nThe message thread is cleared and the AI agent takes the chat back "
      + "(useful when a chat got stuck after 'talk to staff'). Customer memory, persona and "
      + "order history are kept."
    )) return;
    try {
      const res = await api<{ removed_messages: number; conversation_status: string }>(
        `/api/conversations/${selected}/reset?clear_memory=false`, { method: "POST" }
      );
      say(true, `Conversation reset (${res.removed_messages} messages cleared) — agent is ${res.conversation_status}.`);
      loadDetail(selected);
      loadList();
    } catch (e) {
      say(false, `Reset failed: ${(e as Error).message}`);
    }
  };

  // Switch the language of the WHOLE conversation. History and memory stay;
  // only the language the agent replies in changes, from the next message on.
  const switchLanguage = async (code: string) => {
    if (!selected || langBusy) return;
    setLangBusy(true);
    try {
      await api(`/api/conversations/${selected}/language`, {
        method: "PUT",
        body: JSON.stringify({ language: code }),
      });
      say(true, `Conversation language set — the agent now replies in ${code.toUpperCase()} (history and memory kept).`);
      loadDetail(selected);
    } catch (e) {
      say(false, `Language switch failed: ${(e as Error).message}`);
    } finally {
      setLangBusy(false);
    }
  };

  const fmtTime = (iso: string | null) =>
    iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";

  const pausedFor = (pausedAt: string | null) => {
    if (!pausedAt) return "";
    const mins = Math.max(0, Math.round((Date.now() - new Date(pausedAt).getTime()) / 60000));
    return mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h ${mins % 60} min`;
  };

  const pausedCount = (convs || []).filter((c) => c.status === "paused").length;
  const handoffNote = !detail || detail.conversation.status !== "paused"
    ? ""
    : autoResumeMin > 0
      ? `Waiting ${pausedFor(detail.conversation.paused_at) || "—"} for a staff reply. If nobody answers, the AI takes this chat back automatically after ${autoResumeMin} min.`
      : "Automatic hand-back is disabled (HANDOFF_AUTO_RESUME_MINUTES=0) — resume it manually when you are done.";

  return (
    <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
      {/* conversation list */}
      <div className="flex flex-col gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && loadList()}
          placeholder="Search customers…"
          aria-label="Search customers"
          className="w-full rounded-full border border-white/10 bg-[#0a0c10] px-4 py-2.5 text-[13px] text-[#e9edef] placeholder-[#6b727d] focus:border-[var(--green)]/50 focus:outline-none"
        />
        {pausedCount > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[#c9a961]/30 bg-[#c9a961]/5 px-3 py-2">
            <span className="text-[11.5px] text-[#c9a961]">
              {pausedCount} chat{pausedCount === 1 ? "" : "s"} with staff — the agent stays silent there.
              {autoResumeMin > 0 && ` Auto-hand-back after ${autoResumeMin} min without a staff reply.`}
            </span>
            <button
              onClick={resumeAll}
              className="btn-ghost ml-auto rounded-full px-3 py-1 text-[11px] text-[#e9edef]"
              title="Hand every paused chat back to the AI agent"
            >
              ▶ Resume all
            </button>
          </div>
        )}
        <div className="max-h-[520px] space-y-2 overflow-y-auto pr-1">
          {convs === null && (
            <div className="mono rounded-2xl border border-white/10 bg-[var(--ink-2)] px-5 py-8 text-center text-[12.5px] text-[var(--dim)]">
              LOADING CONVERSATIONS…
            </div>
          )}
          {convs?.length === 0 && (
            <div className="rounded-2xl border border-dashed border-white/15 bg-[var(--ink-2)] px-5 py-10 text-center">
              <div className="text-[26px]">💬</div>
              <div className="mt-2 text-[14px]">No customer conversations yet.</div>
              <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted)]">
                Message the business WhatsApp number from any phone — the Kapso poller picks it up
                within seconds and the chat appears here with the agent&apos;s reply.
              </p>
            </div>
          )}
          {convs?.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelected(c.id)}
              className={`w-full rounded-xl border px-3.5 py-3 text-left transition-colors ${
                selected === c.id ? "border-[var(--green)]/40 bg-[var(--green)]/[0.06]" : "border-white/10 bg-[var(--ink)] hover:border-white/25"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[13.5px] font-medium">{c.customer_name || c.display_phone}</span>
                {c.unread_count > 0 && (
                  <span className="mono rounded-full bg-[var(--green)] px-2 py-0.5 text-[10px] font-bold text-[#06130c]">
                    {c.unread_count}
                  </span>
                )}
              </div>
              <div className="mt-0.5 truncate text-[12px] text-[var(--muted)]">{c.last_message_preview || "…"}</div>
              <div className="mono mt-1 flex items-center gap-2 text-[10px] text-[var(--dim)]">
                <span>{c.display_phone}</span>
                {c.status === "paused" && (
                  <span className="text-[#c9a961]">
                    ⏸ WITH STAFF{c.paused_at ? ` · ${pausedFor(c.paused_at)}` : ""}
                  </span>
                )}
                {c.last_message_at && <span className="ml-auto">{fmtTime(c.last_message_at)}</span>}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* thread */}
      <div className="min-w-0">
        {!selected || !detail ? (
          <div className="grid h-[520px] place-items-center rounded-2xl border border-dashed border-white/15 text-[13px] text-[var(--dim)]">
            Select a conversation to view the live thread.
          </div>
        ) : (
          <div className="flex h-[520px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0b141a]">
            <div className="flex flex-wrap items-center gap-2 border-b border-white/5 bg-[#1f2c34] px-4 py-2.5">
              <div className="grid h-8 w-8 place-items-center rounded-full bg-[var(--brass)] text-[12px] font-semibold text-[#1d1608]">
                {(detail.customer?.whatsapp_name || detail.conversation.customer_name || detail.conversation.display_phone || "?").slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 leading-tight">
                <div className="truncate text-[13.5px] font-medium text-[#e9edef]">
                  {detail.customer?.whatsapp_name || detail.conversation.customer_name || detail.conversation.display_phone}
                </div>
                <div className="mono text-[10px] text-[#8696a0]">{detail.conversation.display_phone}</div>
              </div>
              <span
                className={`mono ml-auto rounded-full px-2.5 py-1 text-[10px] ${
                  detail.conversation.status === "paused"
                    ? "border border-[#c9a961]/40 bg-[#c9a961]/10 text-[#c9a961]"
                    : "border border-[var(--green)]/40 bg-[var(--green)]/10 text-[var(--green)]"
                }`}
              >
                {detail.conversation.status === "paused" ? "AGENT PAUSED · HUMAN" : "AGENT ACTIVE"}
              </span>
              {detail.conversation.status === "paused" && (
                <button onClick={resumeAgent} className="btn-ghost rounded-full px-3 py-1.5 text-[11.5px]">
                  ▶ Resume agent
                </button>
              )}
              <button
                onClick={resetConversation}
                className="btn-ghost rounded-full px-3 py-1.5 text-[11.5px]"
                title="Clear this thread and hand the chat back to the agent"
              >
                ⟲ Reset chat
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-b border-white/5 bg-[#111b21] px-4 py-2">
              <LanguagePicker
                value={detail.conversation.language}
                onChange={switchLanguage}
                busy={langBusy}
                label="Conversation language"
              />
              {detail.conversation.language_source === "language selection" && (
                <span className="mono text-[10px] text-[#8696a0]">pinned by the customer</span>
              )}
            </div>

            <div ref={scrollRef} className="flex-1 space-y-2 overflow-y-auto px-4 py-3" style={{ backgroundImage: "radial-gradient(rgba(255,255,255,.035) 1px, transparent 1px)", backgroundSize: "14px 14px" }}>
              {thread.map((item) => {
                const direction = item.kind === "msg" ? item.msg.direction : item.direction;
                const sender = item.kind === "msg" ? item.msg.sender : item.sender;
                const at = item.kind === "msg" ? item.msg.created_at : item.created_at;
                const intent = item.kind === "msg" ? item.msg.intent : item.intent;
                const failed = item.kind === "msg" && item.msg.direction === "out"
                  && item.msg.status === "failed";
                return (
                  <div key={item.kind === "msg" ? item.msg.id : item.id}
                       className={`flex ${direction === "in" ? "justify-start" : "justify-end"}`}>
                    <div
                      className={`max-w-[85%] rounded-xl px-3 py-2 text-[12.5px] leading-[1.45] whitespace-pre-line ${
                        direction === "in"
                          ? "rounded-tl-sm bg-[#1f2c34] text-[#e9edef]"
                          : sender === "human"
                            ? "rounded-tr-sm bg-[#1d3a5f] text-[#e9edef]"
                            : "rounded-tr-sm bg-[#005c4b] text-[#e9fdf4]"
                      }`}
                    >
                      {item.kind === "album" ? (
                        <ImageAlbum images={item.images} className="mb-1 min-w-[220px]" />
                      ) : (
                        <>
                          {item.msg.body}
                          {failed && item.msg.error && (
                            <div className="mono mt-1 rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-[9.5px] text-red-300">
                              {item.msg.error.slice(0, 220)}
                            </div>
                          )}
                        </>
                      )}
                      <div className="mono mt-1 flex items-center gap-1.5 text-[9px] text-[#8696a0]">
                        <span>{sender === "human" ? "staff" : sender === "agent" ? "agent" : "customer"}</span>
                        <span>{fmtTime(at)}</span>
                        {failed && <span className="text-red-400" title={item.kind === "msg" ? item.msg.error : ""}>⚠ failed</span>}
                        {intent && <span className="ml-auto">{intent}</span>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="border-t border-white/5 bg-[#0b141a] px-4 py-3">
              {detail.conversation.status === "paused" && (
                <div className="mb-2 rounded-lg border border-[#c9a961]/30 bg-[#c9a961]/5 px-3 py-2 text-[11.5px] text-[#c9a961]">
                  The AI agent is paused for this chat — your replies go out as staff.
                  {handoffNote && <span className="block pt-0.5 text-[11px] opacity-80">{handoffNote}</span>}
                </div>
              )}
              {attached && (
                <div className="mb-2 flex items-center gap-2 rounded-lg border border-[var(--green)]/30 bg-[var(--green)]/[0.07] px-2.5 py-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={attached.url} alt={attached.label} className="h-10 w-10 rounded object-cover" />
                  <span className="min-w-0 flex-1 truncate text-[11.5px] text-[#e9edef]">
                    {attached.label || attached.filename}
                  </span>
                  <button
                    type="button"
                    onClick={() => setAttached(null)}
                    className="mono rounded-md border border-white/10 px-2 py-1 text-[10px] text-[#8696a0] hover:text-[#e9edef]"
                  >
                    remove
                  </button>
                </div>
              )}
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  sendReply();
                }}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) attachFile(f);
                  }}
                />
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  disabled={sending}
                  aria-label="Attach an image"
                  title="Attach an image (sent as a real WhatsApp photo)"
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-white/10 bg-[#0a0c10] text-[#8696a0] transition-colors hover:border-[var(--green)]/50 hover:text-[#e9edef] disabled:opacity-50"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M21.4 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.2-9.19a3 3 0 014.24 4.24l-9.2 9.19a1 1 0 01-1.41-1.41l8.48-8.49" />
                  </svg>
                </button>
                <input
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  disabled={sending}
                  placeholder="Reply as staff (sends via WhatsApp)…"
                  aria-label="Staff reply"
                  className="flex-1 rounded-full border border-white/10 bg-[#0a0c10] px-4 py-2.5 text-[12.5px] text-[#e9edef] placeholder-[#6b727d] focus:border-[var(--green)]/50 focus:outline-none"
                />
                <MicButton
                  lang={LANGUAGE_BCP47[detail.conversation.language] || "en-IN"}
                  onResult={(h) => { setReply(h); setTimeout(sendReply, 0); }}
                  busy={sending}
                />
                <button
                  type="submit"
                  disabled={sending}
                  aria-label="Send"
                  className="btn-primary grid h-9 w-9 shrink-0 place-items-center rounded-full transition-opacity disabled:opacity-50"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M3 11l18-8-8 18-2-8-8-2z" /></svg>
                </button>
              </form>
            </div>
          </div>
        )}

        {detail && detail.memory.length > 0 && (
          <div className="mt-4 rounded-2xl border border-white/10 bg-[var(--ink-2)] p-4">
            <div className="mono mb-2 text-[10.5px] uppercase tracking-[0.14em] text-[var(--dim)]">
              Customer memory (verified facts the agent uses)
            </div>
            <div className="flex flex-wrap gap-2">
              {detail.memory.map((m, i) => (
                <span key={i} className="rounded-full border border-white/10 bg-[var(--ink)] px-3 py-1.5 text-[11.5px]">
                  <span className="text-[var(--dim)]">{m.key}</span> <span className="text-[#e9edef]">{m.value}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
