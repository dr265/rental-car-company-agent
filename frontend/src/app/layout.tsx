import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ZoomRideXX Car Rentals | Driven by comfort, Trusted for cleanliness",
  description:
    "Rent sanitized self-drive and chauffeur-driven cars on 6h, 12h and 24h packages from ₹1,000. Book online in minutes or on WhatsApp — doorstep delivery, fast KYC, no hidden charges.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
