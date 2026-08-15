/**
 * Wyniki portfela (plan kroki 40 i 42): zwrot za okres i wykres indeksu
 * łańcuchowego na tle benchmarku. Server Component — rozpakowuje `params`
 * (Next.js 16: `params` jest `Promise`) i renderuje `PerformanceChart`
 * (Client Component: hooki TanStack Query, ECharts, przełączniki).
 * Ten sam wzorzec co `struktura/page.tsx`.
 *
 * Trasa jest podstroną portfela, nie pozycją nawigacji globalnej: dolny
 * pasek ma sufit pięciu linków przy obecnym układzie (patrz
 * `components/nav/navItems.ts`), a wejście jest z dashboardu portfela —
 * tak samo jak `struktura` i `rynki`.
 *
 * Autoryzację zapewnia `app/portfolios/layout.tsx` (`AuthGuard`).
 */
import { PerformanceChart } from "@/components/charts/PerformanceChart";

type PortfolioPerformancePageProps = {
  params: Promise<{ id: string }>;
};

export default async function PortfolioPerformancePage({
  params,
}: PortfolioPerformancePageProps) {
  const { id } = await params;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
        Wyniki portfela
      </h1>
      <PerformanceChart portfolioId={id} />
    </div>
  );
}
