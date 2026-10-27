import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Shell, themeScript } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "FINN", template: "%s · FINN" },
  description: "FINN filters Indian market filings and prices down to what matters for your portfolio, and researches any NSE company from its own documents.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "FINN", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0b1424",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
