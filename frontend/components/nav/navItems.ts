/**
 * Wspólna lista pozycji nawigacji — dolna nawigacja (mobile) i boczna
 * (desktop) renderują te same linki, patrz CLAUDE.md sekcja 6.
 *
 * `/portfolios` działa (lista portfeli + routing do `/portfolios/[id]`,
 * krok 32). `/struktura` (krok 33) i `/rynki` (krok 34) działają — same
 * wybierają portfel i przekazują do `/portfolios/[id]/...`. `/dashboard`
 * zostaje linkiem placeholder (osobnego ekranu zbiorczego plan nie ma —
 * dashboard żyje pod konkretnym portfelem).
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
