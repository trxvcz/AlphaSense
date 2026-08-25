/**
 * Kalendarz dywidend portfela (plan krok 47, etap 9). Server Component —
 * sam nie ma interakcji, tylko rozpakowuje `params` (Next.js 16: `params`
 * jest `Promise`) i renderuje `DividendCalendarPanel` (Client Component,
 * tam żyją hooki TanStack Query i stan horyzontu).
 *
 * Autoryzację zapewnia `app/portfolios/layout.tsx` (`AuthGuard`) — obejmuje
 * całe `/portfolios/**`.
 *
 * **Brak wpisu w nawigacji globalnej jest świadomy.** `NAV_ITEMS` ma dziś
 * pięć pozycji i to sufit dolnego paska na 375 px (patrz komentarz w
 * `components/nav/navItems.ts`) — szósta wymagałaby przebudowy paska, czyli
 * zmiany poza zakresem tego kroku. Wejście prowadzi z dashboardu portfela,
 * tak samo jak do struktury, wyników i rynków.
 */
import { DividendCalendarPanel } from "@/components/dividends/DividendCalendarPanel";

type PortfolioDividendsPageProps = {
  params: Promise<{ id: string }>;
};

export default async function PortfolioDividendsPage({ params }: PortfolioDividendsPageProps) {
  const { id } = await params;
  return <DividendCalendarPanel portfolioId={id} />;
}
