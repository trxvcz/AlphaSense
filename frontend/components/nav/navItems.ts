/**
 * Wspólna lista pozycji nawigacji — dolna nawigacja (mobile) i boczna
 * (desktop) renderują te same linki, patrz CLAUDE.md sekcja 6.
 *
 * `/portfolios` działa (lista portfeli + routing do `/portfolios/[id]`,
 * krok 32). `/dashboard`, `/struktura` (krok 33) i `/rynki` (krok 34) same
 * wybierają portfel (`PortfolioPicker`) i przekazują do `/portfolios/[id]`
 * lub `/portfolios/[id]/...` — osobnego ekranu ZBIORCZEGO (kilka portfeli
 * naraz) plan nie przewiduje, każdy z tych widoków dotyczy jednego portfela.
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
