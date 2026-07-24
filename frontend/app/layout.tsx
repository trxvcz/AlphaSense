import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { BottomNav } from "@/components/nav/BottomNav";
import { SideNav } from "@/components/nav/SideNav";
import { Providers } from "@/app/providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AlphaSense",
  description:
    "Monitoring i analiza składu portfela inwestycyjnego — wycena, struktura, rynki.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="pl"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full overflow-x-hidden bg-white font-sans text-zinc-900 dark:bg-zinc-950 dark:text-zinc-50">
        <Providers>
          <div className="flex min-h-screen flex-col md:flex-row">
            <SideNav />
            <main className="min-w-0 flex-1 pb-16 md:pb-0">{children}</main>
          </div>
          <BottomNav />
        </Providers>
      </body>
    </html>
  );
}
