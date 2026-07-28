/**
 * Dostęp do `/assets` — jedyne miejsce, które woła `apiFetch` dla tego zasobu
 * (docs/konwencje.md: „Bez fetch rozsianego po komponentach").
 *
 * `GET /assets/search` jest **publiczne** (bez `Authorization`) — aktywa to
 * słownik globalny, nie zasób użytkownika (patrz docstring
 * `backend/app/modules/marketdata/routes.py`). Wołamy je mimo to przez
 * `apiFetch` z domyślnym `auth: true`: nagłówek jest ignorowany przez backend,
 * a wyjątek od reguły „wszystko idzie jednym klientem" kosztowałby więcej niż
 * daje.
 */
import { apiFetch } from "@/lib/api";

/**
 * Świadomie bez `sector`/`country` — backend ich tu nie zwraca, bo mogą być
 * w trakcie uzupełniania w tle. Nie dodawaj pól, których API nie oddaje.
 */
export type AssetSearchResult = {
  id: string;
  symbol: string;
  name: string;
  asset_class: string;
};

/** Minimalna długość zapytania; krócej backend odpowiada 422, nie pustą listą. */
export const ASSET_SEARCH_MIN_LENGTH = 2;

export function searchAssets(query: string): Promise<AssetSearchResult[]> {
  return apiFetch<AssetSearchResult[]>(
    `/assets/search?q=${encodeURIComponent(query)}`,
  );
}
