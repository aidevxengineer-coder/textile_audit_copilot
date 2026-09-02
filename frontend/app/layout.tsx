import type { Metadata, Viewport } from "next";

import { displayFont, sansFont } from "@/lib/fonts";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "AuditReady AI",
    template: "%s | AuditReady AI",
  },
  description:
    "Multimodal pre-audit compliance gap analysis for Pakistani textile and leather exporters, grounded in WRAP, ETI, amfori BSCI, and OEKO-TEX guidance.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#6259C7",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sansFont.variable} ${displayFont.variable}`} data-scroll-behavior="smooth">
      <body>{children}</body>
    </html>
  );
}
