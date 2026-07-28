/**
 * Struktura portfela (plan krok 33): skład wg klasy, sektora, geografii i
 * waluty oraz koncentracja (HHI). Server Component — sam nie ma interakcji,
 * tylko rozpakowuje `params` (Next.js 16: `params` jest `Promise`) i renderuje
 * `PortfolioStructure` (Client Component, tam żyją hooki TanStack Query,
 * przełącznik wymiaru i wykresy). Ten sam wzorzec co `page.tsx` dashboardu.
 *
 * Autoryzację zapewnia `app/portfolios/layout.tsx` (`AuthGuard`) — obejmuje
 * całe `/portfolios/**`.
 */
import { PortfolioStructure } from "@/components/structure/PortfolioStructure";

type PortfolioStructurePageProps = {
  params: Promise<{ id: string }>;
};

export default async function PortfolioStructurePage({ params }: PortfolioStructurePageProps) {
  const { id } = await params;
  return <PortfolioStructure portfolioId={id} />;
}
