/**
 * Preferencja motywu (plan krok 35, „tryb ciemny/jasny").
 *
 * Zwykły moduł z pub/sub — ten sam wzorzec co `lib/auth/tokenStore.ts`, z tego
 * samego powodu: motyw musi być czytelny i zapisywalny spoza drzewa React
 * (skrypt anty-migotanie w `app/layout.tsx` biegnie, zanim React w ogóle
 * wystartuje). Konsumenci reactowi subskrybują przez `useSyncExternalStore`.
 *
 * Trzy stany, nie dwa: `system` (domyślny — idzie za ustawieniem systemu, tak
 * jak aplikacja zachowywała się do tej pory), `light`, `dark`. Gdyby toggle
 * miał tylko dwa stany, użytkownik nie miałby jak wrócić do „idź za systemem"
 * po jednym kliknięciu, a `prefers-color-scheme` przestałby cokolwiek robić.
 *
 * Strategia Tailwind: klasa `dark` na `<html>` (`@custom-variant` w
 * `app/globals.css`), nie `@media (prefers-color-scheme)`. Dzięki temu ręczny
 * wybór wygrywa z systemem; przy `system` klasę ustawiamy sami z `matchMedia`.
 */
export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

/** Klucz w `localStorage`. Zmiana wymaga aktualizacji skryptu w `app/layout.tsx`. */
export const THEME_STORAGE_KEY = "alphasense-theme";

const listeners = new Set<() => void>();

function isThemePreference(value: string | null): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

/** Preferencja zapisana przez użytkownika; `system`, jeśli nic nie wybrał. */
export function getThemePreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    // Prywatny tryb przeglądarki / zablokowane storage — motyw to nie jest
    // funkcja krytyczna, degradujemy do „system" zamiast wywalać widok.
    return "system";
  }
}

function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Motyw faktycznie narysowany: preferencja z `system` rozwinięta do konkretu. */
export function getResolvedTheme(): ResolvedTheme {
  const preference = getThemePreference();
  return preference === "system" ? systemTheme() : preference;
}

/** Nakłada/zdejmuje klasę `dark` na `<html>` zgodnie z aktualną preferencją. */
export function applyTheme(): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", getResolvedTheme() === "dark");
}

export function setThemePreference(preference: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // j.w. — brak persystencji nie może zablokować zmiany motywu w tej sesji.
  }
  applyTheme();
  for (const listener of listeners) listener();
}

/**
 * Subskrypcja dla `useSyncExternalStore`. Nasłuchuje też zmiany ustawienia
 * systemowego — przy preferencji `system` motyw ma się przełączyć bez
 * przeładowania strony.
 */
export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  const mql = window.matchMedia("(prefers-color-scheme: dark)");
  const onSystemChange = () => {
    if (getThemePreference() === "system") {
      applyTheme();
      listener();
    }
  };
  mql.addEventListener("change", onSystemChange);
  return () => {
    listeners.delete(listener);
    mql.removeEventListener("change", onSystemChange);
  };
}
