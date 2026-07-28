"use client";

import { useSyncExternalStore } from "react";

import { getResolvedTheme, subscribeTheme } from "@/lib/theme";

/**
 * Czy aktualnie narysowany jest motyw ciemny.
 *
 * Potrzebne wyłącznie wykresom: ECharts wymaga literalnych kolorów w opcjach,
 * więc jako jedyna część UI musi znać motyw jawnie, zamiast iść za klasami
 * `dark:` Tailwinda (patrz `lib/chartPalette.ts`).
 *
 * Czyta ROZWIĄZANY motyw z `lib/theme.ts`, a nie samo `prefers-color-scheme` —
 * inaczej ręczny wybór w `ThemeToggle` przestawiałby całe UI, ale nie wykresy,
 * które dalej szłyby za ustawieniem systemu. Snapshot serwerowy to `"light"`,
 * bo `localStorage` i `matchMedia` nie istnieją na serwerze.
 *
 * Wydzielone w kroku 33 z `components/charts/ValueChart.tsx` (krok 32), gdzie
 * ten hook powstał — od kroku 33 korzystają z niego cztery wykresy.
 */
export function useIsDarkTheme(): boolean {
  const resolved = useSyncExternalStore(
    subscribeTheme,
    getResolvedTheme,
    () => "light" as const,
  );
  return resolved === "dark";
}
