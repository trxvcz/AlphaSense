/**
 * Wspólna lista pozycji nawigacji — dolna nawigacja (mobile) i boczna
 * (desktop) renderują te same linki, patrz CLAUDE.md sekcja 6.
 *
 * `/portfolios` działa (lista portfeli + routing do `/portfolios/[id]`,
 * patrz przygotowanie pod krok 32). `/dashboard`, `/rynki`, `/struktura`
 * powstają w kolejnych krokach planu (etap 6) — na razie linki placeholder.
 */
export type NavItem = {
  href: string;
  label: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/portfolios", label: "Portfel" },
  { href: "/rynki", label: "Rynki" },
  { href: "/struktura", label: "Struktura" },
];
