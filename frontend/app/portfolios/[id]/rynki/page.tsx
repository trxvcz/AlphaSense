/**
 * Panel „Twoje rynki" (plan krok 34, ADR-102): rynki z realnymi pozycjami,
 * uszeregowane wg wagi, z indeksem referencyjnym każdego z nich. Server
 * Component — sam nie ma interakcji, tylko rozpakowuje `params` (Next.js 16:
 * `params` jest `Promise`) i renderuje `MarketRankingPanel` (Client Component,
 * tam żyją hooki TanStack Query i sparkline'y).
 *
 * Autoryzację zapewnia `app/portfolios/layout.tsx` (`AuthGuard`) — obejmuje
 * całe `/portfolios/**`.
 */
import { MarketRankingPanel } from "@/components/markets/MarketRankingPanel";

type PortfolioMarketsPageProps = {
  params: Promise<{ id: string }>;
};

export default async function PortfolioMarketsPage({ params }: PortfolioMarketsPageProps) {
  const { id } = await params;
  return <MarketRankingPanel portfolioId={id} />;
}
