/**
 * `/assets/[id]` (plan krok 45) — notowania pojedynczego instrumentu.
 *
 * **Świadomie tylko wykres.** Wskaźniki fundamentalne, techniczne i analiza
 * aktywa to Etap 10 planu v3 (Single Asset Analysis) — dokładanie ich tutaj
 * byłoby wejściem w zakres, którego v2 nie obejmuje (CLAUDE.md #3.11).
 *
 * Ta sama trasa obsługuje indeks rynku: indeks jest zwykłym aktywem
 * (`markets.index_asset_id`, ADR-102), a panel „Twoje rynki" zna jego
 * `asset_id` i linkuje wprost tutaj.
 *
 * Server Component — rozpakowuje `params` (Next.js 16: `params` to `Promise`)
 * i oddaje resztę Client Componentowi, wzorzec z kroków 32/33/41b.
 */
import { AssetCandles } from "@/components/charts/AssetCandles";

type AssetPageProps = {
  params: Promise<{ id: string }>;
};

export default async function AssetPage({ params }: AssetPageProps) {
  const { id } = await params;
  return <AssetCandles assetId={id} />;
}
