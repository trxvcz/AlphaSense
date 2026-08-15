/**
 * Feed newsów portfela (plan krok 46, etap 9). Server Component — sam nie ma
 * interakcji, tylko rozpakowuje `params` (Next.js 16: `params` jest
 * `Promise`) i renderuje `NewsFeedPanel` (Client Component, tam żyją hooki
 * TanStack Query i stan filtra sentymentu).
 *
 * Autoryzację zapewnia `app/portfolios/layout.tsx` (`AuthGuard`) — obejmuje
 * całe `/portfolios/**`.
 */
import { NewsFeedPanel } from "@/components/news/NewsFeedPanel";

type PortfolioNewsPageProps = {
  params: Promise<{ id: string }>;
};

export default async function PortfolioNewsPage({ params }: PortfolioNewsPageProps) {
  const { id } = await params;
  return <NewsFeedPanel portfolioId={id} />;
}
