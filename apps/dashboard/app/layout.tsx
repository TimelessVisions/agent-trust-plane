import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Trust Plane — Agent Production Readiness",
  description:
    "A control boundary between agent reasoning and real-world execution: authorization, delegation, provenance, audit, replay, and adversarial evals.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
