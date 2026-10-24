"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

export type AlbumImage = {
  id?: string;
  url: string;
  caption?: string;
  label?: string;
};

/**
 * One swipeable album for a group of pictures — the same pictures that were
 * sent to WhatsApp, shown one at a time with arrows, dots and a caption.
 * Horizontal swipe / trackpad scroll / arrow keys all work.
 */
export default function ImageAlbum({
  images,
  className = "",
  rounded = "rounded-lg",
}: {
  images: AlbumImage[];
  className?: string;
  rounded?: string;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [index, setIndex] = useState(0);
  const count = images.length;
  const firstUrl = images[0]?.url || "";

  const goTo = useCallback((next: number) => {
    const track = trackRef.current;
    if (!track) return;
    const clamped = Math.max(0, Math.min(count - 1, next));
    track.scrollTo({ left: clamped * track.clientWidth, behavior: "smooth" });
  }, [count]);

  const onScroll = useCallback(() => {
    const track = trackRef.current;
    if (!track || !track.clientWidth) return;
    setIndex(Math.round(track.scrollLeft / track.clientWidth));
  }, []);

  useEffect(() => {
    // a new album (new turn) always starts from the first picture
    setIndex(0);
    trackRef.current?.scrollTo({ left: 0 });
  }, [count, firstUrl]);

  if (!count) return null;
  const current = images[Math.min(index, count - 1)] || images[0];

  return (
    <figure className={`relative overflow-hidden ${rounded} bg-black/40 ${className}`}>
      <div
        ref={trackRef}
        onScroll={onScroll}
        className="flex snap-x snap-mandatory overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") { e.preventDefault(); goTo(index - 1); }
          if (e.key === "ArrowRight") { e.preventDefault(); goTo(index + 1); }
        }}
        aria-label={`Photo ${Math.min(index + 1, count)} of ${count}`}
      >
        {images.map((img, i) => (
          <div key={`${img.id || img.url}-${i}`} className="w-full shrink-0 snap-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={img.url}
              alt={img.label || img.caption || `photo ${i + 1}`}
              loading="lazy"
              draggable={false}
              className="h-full max-h-[300px] w-full bg-black/40 object-contain"
            />
          </div>
        ))}
      </div>

      {count > 1 && (
        <>
          <button
            type="button"
            onClick={() => goTo(index - 1)}
            disabled={index === 0}
            aria-label="Previous photo"
            className="absolute left-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full bg-black/55 text-[13px] text-white/90 backdrop-blur transition-opacity hover:bg-black/75 disabled:pointer-events-none disabled:opacity-0"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => goTo(index + 1)}
            disabled={index >= count - 1}
            aria-label="Next photo"
            className="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full bg-black/55 text-[13px] text-white/90 backdrop-blur transition-opacity hover:bg-black/75 disabled:pointer-events-none disabled:opacity-0"
          >
            ›
          </button>
          <span className="mono absolute right-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[9px] text-white/90">
            {Math.min(index + 1, count)}/{count}
          </span>
        </>
      )}

      {(current?.label || current?.caption) && (
        <figcaption className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/45 to-transparent px-3 pb-2 pt-6 text-[11px] leading-snug text-white">
          {current.label && <span className="block font-medium">{current.label}</span>}
          {current.caption && current.caption !== current.label && (
            <span className="block text-[10px] text-white/75">{current.caption}</span>
          )}
        </figcaption>
      )}

      {count > 1 && (
        <div className="absolute inset-x-0 bottom-1 flex justify-center gap-1" aria-hidden>
          {images.slice(0, 24).map((_, i) => (
            <span
              key={i}
              className={`h-1 rounded-full transition-all ${
                i === index ? "w-3 bg-white/90" : "w-1 bg-white/35"
              }`}
            />
          ))}
        </div>
      )}
    </figure>
  );
}
