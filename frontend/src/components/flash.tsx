"use client";

import React, { useEffect, useState } from "react";

let _flashSetter: ((f: { ok: boolean; msg: string } | null) => void) | null = null;

/** Show a success/error banner in the console section. */
export function say(ok: boolean, msg: string) {
  _flashSetter?.({ ok, msg });
}

export function FlashHost() {
  const [flash, setFlash] = useState<{ ok: boolean; msg: string } | null>(null);
  useEffect(() => {
    _flashSetter = setFlash;
    return () => { _flashSetter = null; };
  }, []);
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);
  if (!flash) return null;
  return (
    <div
      className={`mt-5 rounded-xl border px-4 py-3 text-[13px] ${
        flash.ok
          ? "border-[var(--green)]/30 bg-[var(--green)]/10 text-[var(--green)]"
          : "border-red-500/30 bg-red-500/10 text-red-300"
      }`}
    >
      {flash.msg}
    </div>
  );
}
