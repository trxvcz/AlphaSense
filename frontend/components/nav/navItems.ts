/**
 * Wspólna lista pozycji nawigacji — dolna nawigacja (mobile) i boczna
 * (desktop) renderują te same linki, patrz CLAUDE.md sekcja 6.
 *
 * Trasy `/portfel`, `/rynki`, `/struktura` powstają w kolejnych etapach
 * planu (etap 5–6) — na razie to same linki placeholder.
 */
export type NavItem = {
  href: string;
  label: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/portfel", label: "Portfel" },
  { href: "/rynki", label: "Rynki" },
  { href: "/struktura", label: "Struktura" },
];
