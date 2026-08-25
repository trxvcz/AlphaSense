/**
 * Ryzyko portfela (plan krok 41b): zmienność, Sharpe, max drawdown
 * z wykresem underwater, beta i heatmapa zwrotów miesięcznych.
 *
 * Osobna podstrona, a NIE sekcja na dashboardzie: główny dashboard trzyma
 * zasadę 5–7 KPI (CLAUDE.md §21), a to jest pięć kolejnych wskaźników
 * i dwa wykresy. Wejście jest z dashboardu portfela, tak jak `wyniki`
 * i `struktura`.
 *
 * Server Component — rozpakowuje `params` (Next.js 16: `params` jest
 * `Promise`) i renderuje `RiskPanel` (Client: hooki TanStack Query,
 * ECharts, przełączniki). Autoryzację zapewnia `app/portfolios/layout.tsx`.
 */
import { RiskPanel } from "@/components/dashboard/RiskPanel";

type PortfolioRiskPageProps = {
  params: Promise<{ id: string }>;
};

export default async function PortfolioRiskPage({ params }: PortfolioRiskPageProps) {
  const { id } = await params;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
        Ryzyko portfela
      </h1>
      <RiskPanel portfolioId={id} />
    </div>
  );
}
