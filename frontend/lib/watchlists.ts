/**
 * Dostęp do list obserwowanych (`/watchlists`, krok 43, etap 8).
 *
 * **Watchlista to nie drugi portfel** (CLAUDE.md #3.11): pozycja listy nie ma
 * ilości ani wyceny i nie może ich tu dostać „przy okazji" — obserwowanie nie
 * jest posiadaniem. Kształty 1:1 z `docs/api-kontrakt.md`.
 */
import { apiFetch } from "@/lib/api";

export type Watchlist = {
  id: string;
  name: string;
  created_at: string;
  item_count: number;
};

export type WatchlistItem = {
  asset_id: string;
  symbol: string;
  name: string;
  market_code: string;
  currency: string;
  /** Notatka użytkownika („czekam na wyniki Q3") — nie dana rynkowa. */
  note: string | null;
  added_at: string;
};

export function getWatchlists(): Promise<Watchlist[]> {
  return apiFetch<Watchlist[]>("/watchlists");
}

export function createWatchlist(name: string): Promise<Watchlist> {
  return apiFetch<Watchlist>("/watchlists", { method: "POST", body: { name } });
}

export function deleteWatchlist(watchlistId: string): Promise<void> {
  return apiFetch<void>(`/watchlists/${watchlistId}`, { method: "DELETE" });
}

export function getWatchlistItems(watchlistId: string): Promise<WatchlistItem[]> {
  return apiFetch<WatchlistItem[]>(`/watchlists/${watchlistId}/items`);
}

/** Idempotentne — powtórne dodanie aktualizuje notatkę zamiast zgłaszać błąd. */
export function addWatchlistItem(
  watchlistId: string,
  assetId: string,
  note: string | null,
): Promise<void> {
  return apiFetch<void>(`/watchlists/${watchlistId}/items/${assetId}`, {
    method: "PUT",
    body: { note },
  });
}

export function removeWatchlistItem(watchlistId: string, assetId: string): Promise<void> {
  return apiFetch<void>(`/watchlists/${watchlistId}/items/${assetId}`, { method: "DELETE" });
}
