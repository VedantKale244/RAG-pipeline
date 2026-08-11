import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "../lib/auth-context";

export const metadata: Metadata = {
  title: "Neuro-Adaptive GraphRAG | Enterprise AI Intelligence Platform",
  description:
    "Enterprise GraphRAG & Vector Search Pipeline with Adaptive Graph Reweighting",
  icons: {
    icon: "/favicon.ico",
    shortcut: "/favicon.ico",
    apple: "/icon.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" href="/icon.png" type="image/png" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen antialiased relative" suppressHydrationWarning>
        {/* Background Wallpaper */}
        <div
          className="fixed inset-0 -z-10 pointer-events-none bg-cover bg-center bg-no-repeat"
          style={{ backgroundImage: "url('/custom-bg.jpg')" }}
        />
        {/* Soft light overlay to keep text readable while showing the photo */}
        <div className="fixed inset-0 -z-10 pointer-events-none" style={{ background: 'linear-gradient(180deg, rgba(235,244,251,0.55) 0%, rgba(240,248,255,0.35) 50%, rgba(235,244,251,0.55) 100%)' }} />
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
