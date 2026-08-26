/**
 * Dostęp do zasobów modułu `analytics` (`allocation`, `concentration`) —
 * jedyne miejsce, które woła `apiFetch` dla tych zasobów (docs/konwencje.md:
 * „Bez fetch rozsianego po komponentach"). Widoki wołają te funkcje przez
 * TanStack Query z kluczami z `lib/queryKeys.ts`.
 *
 * Kształty odpowiedzi 1:1 z `docs/api-kontrakt.md` i `analytics/schemas.py` —
 * kwoty i wagi to STRINGI dziesiętne, nie `number` (CLAUDE.md #3.1).
 *
 * Ranking rynków (`GET /portfolios/{id}/markets`, krok 34) też tutaj — to ta
 * sama rodzina endpointów (router `analytics`), mimo że karmi osobny widok.
 */
import { apiFetch } from "@/lib/api";

/**
 * Wymiary przyjmowane przez `?by=` (`AllocationDimensionParam` w
 * `analytics/routes.py`). `market` jest w API, ale widok struktury go nie
 * pokazuje — rynki dostają własny panel w kroku 34, z indeksami referencyjnymi,
 * czego sama alokacja nie zwraca.
 */
export type AllocationDimension = "class" | "sector" | "geo" | "currency" | "market";

export type AllocationBucket = {
  key: string;
  value_pln: string;
  weight: string;
};

export type Allocation = {
  by: string;
  as_of: string;
  approximate: boolean;
  buckets: AllocationBucket[];
};

export type Concentration = {
  top5_share: string;
  count: number;
  hhi: string;
  /** `"niska" | "średnia" | "wysoka"` — progi HHI liczy backend, nie UI. */
  interpretation: string;
};

/**
 * `by` jest wymagany — backend nie ma wartości domyślnej i na brak parametru
 * zwraca 422 (decyzja udokumentowana w `analytics/routes.py`: lepiej odmówić
 * niż zgadywać, którą alokację użytkownik chciał zobaczyć). Domyślny wymiar
 * przy wejściu na widok wybiera frontend, patrz `DEFAULT_DIMENSION`.
 */
export function getAllocation(
  portfolioId: string,
  by: AllocationDimension,
  tags: string | null = null,
): Promise<Allocation> {
  // `tags` (krok 43) zawęża portfel do aktywów z którymkolwiek z tych tagów
  // (OR) PRZED policzeniem wag — wagi sumują się do 100% w obrębie tego, co
  // filtr przepuścił. Wartość buduje `serializeTagFilter` (`lib/tags.ts`).
  const suffix = tags ? `&tags=${encodeURIComponent(tags)}` : "";
  return apiFetch<Allocation>(`/portfolios/${portfolioId}/allocation?by=${by}${suffix}`);
}

export function getConcentration(portfolioId: string): Promise<Concentration> {
  return apiFetch<Concentration>(`/portfolios/${portfolioId}/concentration`);
}

/** Punkt serii notowań indeksu (`PricePointOut` w `marketdata/schemas.py`). */
export type PricePoint = {
  date: string;
  close_adj: string;
};

/**
 * Zmiana d/d indeksu — liczona z dwóch najnowszych wierszy `prices`, nie ze
 * snapshotów portfela (stąd osobny typ niż `Change` w `lib/dashboard.ts`).
 * `null`, gdy indeks ma w bazie tylko jedno notowanie.
 */
export type IndexChange = {
  abs: string;
  pct: string;
};

export type MarketIndex = {
  asset_id: string;
  symbol: string;
  value: string;
  change_1d: IndexChange | null;
  as_of: string;
  /** Do 30 OSTATNICH DOSTĘPNYCH notowań, nie 30 dni kalendarzowych. */
  series_30d: PricePoint[];
};

export type MarketRankingItem = {
  market_code: string;
  market_name: string;
  weight: string;
  /**
   * `null`, gdy rynek nie ma indeksu referencyjnego w słowniku ALBO gdy ma,
   * ale worker EOD nie zaciągnął jeszcze dla niego żadnego notowania. Widok
   * nie odróżnia tych dwóch przypadków — API ich nie rozróżnia, a dla
   * użytkownika oba znaczą to samo: nie ma czego narysować.
   */
  index: MarketIndex | null;
};

/** Rynki posortowane malejąco po wadze — kolejność z backendu, nie sortujemy ponownie. */
export function getMarketRanking(portfolioId: string): Promise<MarketRankingItem[]> {
  return apiFetch<MarketRankingItem[]>(`/portfolios/${portfolioId}/markets`);
}
