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

/**
 * Skrypt anty-migotanie (plan krok 35). Musi wykonać się SYNCHRONICZNIE przed
 * pierwszym malowaniem, inaczej użytkownik z motywem ciemnym zobaczy błysk
 * białego tła: `dark:` jest sterowane klasą (`app/globals.css`), a serwer nie
 * zna ani `localStorage`, ani `prefers-color-scheme`, więc HTML z serwera jest
 * zawsze „jasny". Stąd inline `<script>` w `<head>`, a nie `useEffect`.
 *
 * Celowo nie importuje `lib/theme.ts` — to musi być samodzielny string, bo
 * biegnie zanim jakikolwiek bundel się załaduje. Klucz `alphasense-theme` jest
 * zduplikowany względem `THEME_STORAGE_KEY`; zmiana wymaga ruszenia obu miejsc
 * (świadomie, alternatywą byłoby wstrzykiwanie bundla tylko po to, żeby
 * odczytać jeden klucz).
 */
const THEME_INIT_SCRIPT = `
try {
  var p = localStorage.getItem("alphasense-theme");
  var dark = p === "dark" || ((p === null || p === "system") &&
    window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
} catch (e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="pl"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
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
