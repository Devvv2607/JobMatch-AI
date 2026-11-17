import type { Metadata } from "next";
import { Inter_Tight, JetBrains_Mono, Newsreader } from "next/font/google";

import { Providers } from "./providers";
import "./globals.css";

const newsreader = Newsreader({ subsets: ["latin"], variable: "--font-newsreader" });
const interTight = Inter_Tight({ subsets: ["latin"], variable: "--font-inter-tight" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono" });

export const metadata: Metadata = {
  title: "JobMatch",
  description: "The few jobs that fit, each with the reason and the gaps.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${newsreader.variable} ${interTight.variable} ${jetbrainsMono.variable} antialiased`}
    >
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
