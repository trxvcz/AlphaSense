"use client";

/**
 * Baner „dane z {data}, offline" (plan krok 49, etap 9).
 *
 * Oznaczenie jakości danych, nie ozdoba (CLAUDE.md #3.15) — bez sieci
 * użytkownik patrzy na zrzut sprzed jakiegoś czasu i musi to wiedzieć,
 * zanim wyciągnie wniosek z liczby na ekranie.
 *
 * Dostępność (§21): komunikat niesie **tekst**, nie sam kolor, i siedzi w
 * `role="status"`, więc czytnik ekranu ogłosi go bez przenoszenia fokusu.
 */
import { bannerText } from "@/lib/offline/bannerText";
import { useOfflineCache } from "@/lib/offline/OfflineCacheProvider";

export function OfflineBanner() {
  const { savedAt, isOnline } = useOfflineCache();
  const text = bannerText({ savedAt, isOnline });
  if (text === null) return null;

  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
    >
      <span aria-hidden="true">⚠</span>
      <span>{text}</span>
    </div>
  );
}
