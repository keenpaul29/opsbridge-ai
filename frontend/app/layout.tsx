import type { Metadata } from "next";
import Link from "next/link";
import { Barlow_Condensed, Instrument_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const sans = Instrument_Sans({ variable: "--font-instrument-sans", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-jetbrains-mono", subsets: ["latin"] });
const stamp = Barlow_Condensed({
  variable: "--font-barlow-condensed",
  subsets: ["latin"],
  weight: ["600", "700"],
});

export const metadata: Metadata = {
  title: "OpsBridge AI — Operator Console",
  description: "Triage queue, agent traces and approvals",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${sans.variable} ${mono.variable} ${stamp.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-sans">
        <header className="border-b border-ink bg-surface">
          <nav className="mx-auto flex h-11 max-w-[1040px] items-center gap-6 px-6">
            <span className="font-stamp text-lg font-bold uppercase tracking-wider">OpsBridge</span>
            <Link href="/" className="font-medium hover:underline">
              Triage Queue
            </Link>
            <Link href="/evals" className="font-medium hover:underline">
              Eval Dashboard
            </Link>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-[1040px] flex-1 px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
