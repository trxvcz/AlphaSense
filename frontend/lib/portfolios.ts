/**
 * Dostęp do `/portfolios` — jedyne miejsce, które woła `apiFetch` dla tego
 * zasobu (docs/konwencje.md: „Bez fetch rozsianego po komponentach").
 * Widoki wołają te funkcje przez TanStack Query z kluczami z
 * `lib/queryKeys.ts`.
 */
import { apiFetch } from "@/lib/api";

export type Portfolio = {
  id: string;
  name: string;
  type: string;
  holdings_version: number;
  created_at: string;
};

export type CreatePortfolioInput = {
  name: string;
  type: string;
};

export function listPortfolios(): Promise<Portfolio[]> {
  return apiFetch<Portfolio[]>("/portfolios");
}

export function getPortfolio(portfolioId: string): Promise<Portfolio> {
  return apiFetch<Portfolio>(`/portfolios/${portfolioId}`);
}

export function createPortfolio(input: CreatePortfolioInput): Promise<Portfolio> {
  return apiFetch<Portfolio>("/portfolios", {
    method: "POST",
    body: input,
  });
}
