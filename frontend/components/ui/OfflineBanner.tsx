"use client";

/**
 * Baner „dane z {data}, offline" (plan krok 49, etap 9; treść z katalogu
 * komunikatów od kroku 50).
 *
 * Oznaczenie jakości danych, nie ozdoba (CLAUDE.md #3.15) — bez sieci
 * użytkownik patrzy na zrzut sprzed jakiegoś czasu i musi to wiedzieć,
 * zanim wyciągnie wniosek z liczby na ekranie.
 *
 * Dostępność (§21): komunikat niesie **tekst**, nie sam kolor, i siedzi w
 * `role="status"`, więc czytnik ekranu ogłosi go bez przenoszenia fokusu.
 */
import { useTranslations } from "next-intl";
import { bannerMessage } from "@/lib/offline/bannerText";
import { useOfflineCache } from "@/lib/offline/OfflineCacheProvider";

export function OfflineBanner() {
  const t = useTranslations("offline.banner");
  const { savedAt, isOnline } = useOfflineCache();
  const message = bannerMessage({ savedAt, isOnline });
  if (message === null) return null;

  // Wiek zrzutu tłumaczymy osobno i wstawiamy jako parametr — po polsku to
  // od niego zależy przyimek („sprzed 30 min" vs „z godz. 11:00").
  const text =
    message.key === "noData"
      ? t("noData")
      : t("withAge", { age: t(message.age.key, message.age.values) });

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
