"use client";

/**
 * Przełącznik motywu (plan krok 35). Cykl `system → jasny → ciemny → system`
 * jednym przyciskiem — na 375 px nie ma miejsca na trzy osobne kontrolki, a
 * rozwijana lista dla trzech wartości byłaby cięższa niż zysk.
 *
 * Stan czytany przez `useSyncExternalStore` z `lib/theme.ts`, żeby przycisk
 * w `SideNav` i w `BottomNav` (dwie instancje) zawsze pokazywały to samo.
 */
import { useSyncExternalStore } from "react";
import {
  getThemePreference,
  setThemePreference,
  subscribeTheme,
  type ThemePreference,
} from "@/lib/theme";

const NEXT_PREFERENCE: Record<ThemePreference, ThemePreference> = {
  system: "light",
  light: "dark",
  dark: "system",
};

const LABEL: Record<ThemePreference, string> = {
  system: "Motyw: systemowy",
  light: "Motyw: jasny",
  dark: "Motyw: ciemny",
};

// Znaki zamiast biblioteki ikon — repo nie ma żadnej, a dokładanie zależności
// dla trzech glifów byłoby nieproporcjonalne (CLAUDE.md #10).
const GLYPH: Record<ThemePreference, string> = {
  system: "◐",
  light: "☀",
  dark: "☾",
};

// Serwer nie zna preferencji (żyje w localStorage) — pierwszy render zakłada
// „system", a `useSyncExternalStore` poprawi go zaraz po hydratacji. Sam motyw
// jest już wtedy poprawnie narysowany przez skrypt z `app/layout.tsx`.
function getServerSnapshot(): ThemePreference {
  return "system";
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  const preference = useSyncExternalStore(
    subscribeTheme,
    getThemePreference,
    getServerSnapshot,
  );

  return (
    <button
      type="button"
      onClick={() => setThemePreference(NEXT_PREFERENCE[preference])}
      aria-label={`${LABEL[preference]}. Kliknij, żeby przełączyć.`}
      title={LABEL[preference]}
      className={`rounded-md px-2 py-1 text-sm text-zinc-700 outline-offset-2 hover:bg-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-300 dark:hover:bg-zinc-800 ${className}`}
    >
      <span aria-hidden="true">{GLYPH[preference]}</span>
    </button>
  );
}
