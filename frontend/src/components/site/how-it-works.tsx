"use client";

/* How it works + trust strip — static content from the published process. */
import React from "react";
import { Icon } from "@/components/site/icons";

const STEPS = [
  {
    n: 1,
    title: "Choose Your Car",
    body: "Select from our sanitized fleet based on your required hours (6h, 12h, or 24h) — right here on the site, on WhatsApp, or with Karan.",
    accent: "zoomBlue" as const,
  },
  {
    n: 2,
    title: "Quick Verification",
    body: "Share your Driving Licence & Aadhaar on WhatsApp. A 5-minute digital check — or show originals at handover.",
    accent: "zoomGold" as const,
  },
  {
    n: 3,
    title: "Drive Away Clean",
    body: "Collect the keys from our hub or opt for doorstep delivery straight to your home or hotel.",
    accent: "emerald" as const,
  },
];

const ACCENTS = {
  zoomBlue: "bg-zoomBlue-500/10 text-zoomBlue-400 border-zoomBlue-500/30",
  zoomGold: "bg-zoomGold-500/10 text-zoomGold-400 border-zoomGold-500/30",
  emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
};

export function HowItWorks() {
  return (
    <section id="how-it-works" className="py-16 bg-black/50 border-y border-slate-800 scroll-mt-28">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-12">
          <span className="text-zoomGold-400 font-heading text-xs uppercase tracking-widest font-bold">Simple 3-Step Process</span>
          <h2 className="font-heading text-3xl font-extrabold text-white mt-1">How ZoomRideXX Works</h2>
          <p className="text-slate-400 text-xs sm:text-sm mt-2">
            Book here on the website or on WhatsApp — the same fleet desk handles both.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {STEPS.map((s) => (
            <div key={s.n} className="p-6 glass-card rounded-lg text-center">
              <div className={`w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4 border ${ACCENTS[s.accent]}`}>
                <span className="font-heading font-extrabold text-lg">{s.n}</span>
              </div>
              <h3 className="font-heading text-lg font-bold text-white">{s.title}</h3>
              <p className="text-slate-400 text-xs mt-2 leading-relaxed">{s.body}</p>
            </div>
          ))}
        </div>

        <div className="mt-12 grid grid-cols-2 md:grid-cols-4 gap-3 max-w-4xl mx-auto text-center">
          {[
            { icon: "shield" as const, label: "Sanitized before every trip" },
            { icon: "clock" as const, label: "30-minute doorstep delivery" },
            { icon: "briefcase" as const, label: "Refundable deposit, no cuts" },
            { icon: "phone" as const, label: "24/7 roadside assistance" },
          ].map((t) => (
            <div key={t.label} className="glass-card rounded-lg p-4">
              <Icon name={t.icon} className="w-5 h-5 mx-auto text-zoomGold-400 mb-2" />
              <p className="text-[11px] text-slate-300 font-medium">{t.label}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
