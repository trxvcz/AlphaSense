/**
 * Dashboard portfela (plan krok 32): łączna wartość, zmiana 1D/YTD, wykres
 * wartości (ECharts) i top ruchy dnia. Server Component — sam nie ma
 * interakcji, tylko rozpakowuje `params` (Next.js 16: `params` jest
 * `Promise`) i renderuje `PortfolioDashboard` (Client Component, tam żyją
 * hooki TanStack Query i wykres).
 */
import { PortfolioDashboard } from "@/components/dashboard/PortfolioDashboard";

type PortfolioDetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function PortfolioDetailPage({ params }: PortfolioDetailPageProps) {
  const { id } = await params;
  return <PortfolioDashboard portfolioId={id} />;
}
