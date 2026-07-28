/**
 * Dostęp do zasobów dashboardu portfela (`summary`, `valuations`, `holdings`)
 * — jedyne miejsce, które woła `apiFetch` dla tych zasobów
 * (docs/konwencje.md: „Bez fetch rozsianego po komponentach"). Widoki wołają
 * te funkcje przez TanStack Query z kluczami z `lib/queryKeys.ts`.
 *
 * Kształty odpowiedzi 1:1 z `docs/api-kontrakt.md` — nie dodawaj pól, których
 * backend nie zwraca.
 */
import { apiFetch } from "@/lib/api";

export type Change = {
  abs: string;
  pct: string;
};

export type PortfolioSummary = {
  value_pln: string;
  change_1d: Change | null;
  change_ytd: Change | null;
  as_of: string;
  stale_assets: number;
};

export type ValuationPoint = {
  date: string;
  value_pln: string;
  composition_change: boolean;
};

export type ValuationRange = "1M" | "3M" | "1Y" | "YTD" | "max";

export type Holding = {
  id: string;
  asset_id: string;
  symbol: string;
  quantity: string;
  avg_cost: string | null;
  cost_currency: string | null;
  note: string | null;
  value_pln: string | null;
  stale: boolean;
  as_of: string | null;
  unrealized_pl: string | null;
  split_suspected: boolean;
  price_change_1d: Change | null;
};

export function getSummary(portfolioId: string): Promise<PortfolioSummary> {
  return apiFetch<PortfolioSummary>(`/portfolios/${portfolioId}/summary`);
}

export function listValuations(
  portfolioId: string,
  range: ValuationRange,
): Promise<ValuationPoint[]> {
  return apiFetch<ValuationPoint[]>(
    `/portfolios/${portfolioId}/valuations?range=${range}`,
  );
}

export function listHoldings(portfolioId: string): Promise<Holding[]> {
  return apiFetch<Holding[]>(`/portfolios/${portfolioId}/holdings`);
}

/**
 * Wejście `POST /portfolios/{id}/holdings` (plan krok 35).
 *
 * Kwoty jako STRINGI, nie `number` — backend przyjmuje `Decimal` i to samo
 * ograniczenie co przy odczycie obowiązuje przy zapisie (CLAUDE.md #3.1):
 * `0.1` w `number` nie jest dokładnie 0,1, a przy ilościach krypto
 * (8 miejsc po przecinku) to realna różnica, nie teoria.
 *
 * `avg_cost` i `cost_currency` są opcjonalne, ale RAZEM — backend zwraca 422,
 * jeśli podasz cenę bez waluty (`HoldingCreateIn._avg_cost_needs_currency`).
 */
export type CreateHoldingInput = {
  asset_id: string;
  quantity: string;
  avg_cost?: string;
  cost_currency?: string;
  note?: string;
};

export function createHolding(
  portfolioId: string,
  input: CreateHoldingInput,
): Promise<Holding> {
  return apiFetch<Holding>(`/portfolios/${portfolioId}/holdings`, {
    method: "POST",
    body: input,
  });
}
