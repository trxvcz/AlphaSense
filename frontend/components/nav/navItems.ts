/**
 * Wspólna lista pozycji nawigacji — dolna nawigacja (mobile) i boczna
 * (desktop) renderują te same linki, patrz CLAUDE.md sekcja 6.
 *
 * `/portfolios` działa (lista portfeli + routing do `/portfolios/[id]`,
 * krok 32). `/dashboard`, `/struktura` (krok 33), `/rynki` (krok 34) i
 * `/newsy` (krok 46) same wybierają portfel (`PortfolioPicker`) i przekazują
 * do `/portfolios/[id]` lub `/portfolios/[id]/...` — osobnego ekranu
 * ZBIORCZEGO (kilka portfeli naraz) plan nie przewiduje, każdy z tych widoków
 * dotyczy jednego portfela.
 *
 * **Pięć pozycji to sufit tej listy przy obecnym układzie dolnego paska.**
 * `BottomNav` dzieli szerokość między linki, konto i przełącznik motywu —
 * na 375 px daje to ok. 55 px na link, co mieści najdłuższą etykietę
 * („Struktura", zmierzone zrzutem Playwrighta w kroku 46). Szósta pozycja
 * wymaga zmiany układu paska (zwijanie do „więcej"), nie samego dopisania
 * wiersza tutaj.
 */
export type NavItem = {
  href: string;
  /** Klucz w przestrzeni `nav` katalogu komunikatów (krok 50) — nie gotowa
   * etykieta: tekst mieszka w `messages/pl.json`, patrz `lib/i18n.ts`. */
  labelKey: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", labelKey: "dashboard" },
  { href: "/portfolios", labelKey: "portfolios" },
  { href: "/rynki", labelKey: "markets" },
  { href: "/struktura", labelKey: "structure" },
  { href: "/newsy", labelKey: "news" },
];
