/**
 * Dostęp do zasobów modułu `analytics` (`allocation`, `concentration`) —
 * jedyne miejsce, które woła `apiFetch` dla tych zasobów (docs/konwencje.md:
 * „Bez fetch rozsianego po komponentach"). Widoki wołają te funkcje przez
 * TanStack Query z kluczami z `lib/queryKeys.ts`.
 *
 * Kształty odpowiedzi 1:1 z `docs/api-kontrakt.md` i `analytics/schemas.py` —
 * kwoty i wagi to STRINGI dziesiętne, nie `number` (CLAUDE.md #3.1).
 *
 * Ranking rynków (`GET /portfolios/{id}/markets`) świadomie NIE jest tutaj —
 * to krok 34 planu (panel „Twoje rynki"), osobny widok i osobny kształt danych.
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
): Promise<Allocation> {
  return apiFetch<Allocation>(`/portfolios/${portfolioId}/allocation?by=${by}`);
}

export function getConcentration(portfolioId: string): Promise<Concentration> {
  return apiFetch<Concentration>(`/portfolios/${portfolioId}/concentration`);
}
