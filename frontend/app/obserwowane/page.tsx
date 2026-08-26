/**
 * `/obserwowane` (plan krok 43b) — listy obserwowanych.
 *
 * Bez wyboru portfela, inaczej niż `/struktura` czy `/rynki`: watchlista
 * należy do użytkownika, nie do portfela (`watchlists.user_id`), więc nie ma
 * o co pytać przed wejściem.
 *
 * **Bez wpisu w nawigacji globalnej** — `NAV_ITEMS` ma pięć pozycji i to sufit
 * dolnego paska na 375 px (`components/nav/navItems.ts`). Wejście prowadzi
 * z dashboardu portfela, tak samo jak do kalendarza dywidend (krok 47).
 *
 * Server Component: cała interakcja żyje w `WatchlistsView`.
 */
import { WatchlistsView } from "@/components/watchlist/WatchlistsView";

export default function ObserwowanePage() {
  return <WatchlistsView />;
}
