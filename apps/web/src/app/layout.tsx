import type { Metadata, Viewport } from "next";
import { Anek_Latin, Hind } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

// Both faces come from Indian type foundries (Ek Type, ITF) and have Gujarati and
// Devanagari companions, which the multilingual phase can switch to without a redesign.
const anek = Anek_Latin({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-anek",
  display: "swap",
});
const hind = Hind({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-hind",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "MoneyMoney", template: "%s · MoneyMoney" },
  description: "Track what you spend and earn by just telling it.",
};

export const viewport: Viewport = {
  themeColor: "#f6f5f9",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-IN" className={`${anek.variable} ${hind.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
