import type { Metadata } from "next";

import { Providers } from "@/components/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "SOA Next Dashboard",
  description: "Parallel Next.js frontend for Super Order Automation",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html dir="rtl" lang="he">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
