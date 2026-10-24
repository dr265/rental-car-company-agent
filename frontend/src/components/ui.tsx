"use client";

import React from "react";

export function StatusPill({
  ok,
  pending,
  label,
  onClick,
  title,
}: {
  ok: boolean | null;
  pending?: boolean;
  label: string;
  onClick?: () => void;
  title?: string;
}) {
  const dot =
    ok === null || pending
      ? "bg-brass"
      : ok
        ? "bg-jewel"
        : "bg-red-500";
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`mono inline-flex items-center gap-2 rounded-full border border-white/10 bg-ink2 px-3 py-1.5 text-[11px] tracking-wide text-ivory/90 ${onClick ? "cursor-pointer hover:border-white/25" : "cursor-default"}`}
    >
      <span className={`h-2 w-2 rounded-full ${dot} ${ok === null || pending ? "animate-pulse" : ""}`} />
      {label}
    </button>
  );
}

export function Flash({ flash }: { flash: { ok: boolean; msg: string } | null }) {
  if (!flash) return null;
  return (
    <div
      className={`rounded-xl border px-4 py-3 text-[13px] ${
        flash.ok
          ? "border-jewel/30 bg-jewel/10 text-jewel"
          : "border-red-500/30 bg-red-500/10 text-red-300"
      }`}
    >
      {flash.msg}
    </div>
  );
}

export function Section({
  title,
  subtitle,
  children,
  right,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-white/10 bg-ink2/60 p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-[16px] font-medium">{title}</h3>
          {subtitle && <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-ivory/60">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
  onEnter,
  className = "",
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  onEnter?: () => void;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <input
      type={type}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
      placeholder={placeholder}
      className={`w-full rounded-xl border border-white/10 bg-ink px-3.5 py-2.5 text-[13.5px] text-ivory placeholder:text-white/30 outline-none transition-colors focus:border-jewel/60 ${className}`}
    />
  );
}

export function GhostButton({
  children,
  onClick,
  disabled,
  title,
  className = "",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded-xl border border-white/10 px-3.5 py-2 text-[12.5px] text-ivory/80 transition-colors hover:border-white/25 hover:text-ivory disabled:opacity-40 ${className}`}
    >
      {children}
    </button>
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
  className = "",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-xl bg-jewel px-4 py-2 text-[13px] font-semibold text-[#06130c] transition-opacity hover:opacity-90 disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  );
}

export function EmptyState({ icon, title, hint }: { icon: string; title: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-white/15 px-4 py-8 text-center">
      <div className="text-[24px]">{icon}</div>
      <div className="mt-2 text-[13.5px]">{title}</div>
      {hint && <p className="mx-auto mt-1 max-w-sm text-[12.5px] leading-relaxed text-ivory/50">{hint}</p>}
    </div>
  );
}
