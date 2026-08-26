"use client";

/**
 * Ekran notowań instrumentu (plan krok 45) — nagłówek z powrotem i panel
 * świecowy. Client Component: stan zakresu i hooki TanStack Query żyją
 * w `CandlePanel`.
 */
import Link from "next/link";

import { getAssetCandles, type CandleRange } from "@/lib/candles";
import { qk } from "@/lib/queryKeys";
import { CandlePanel } from "@/components/charts/CandlePanel";

type AssetCandlesProps = {
  assetId: string;
};

export function AssetCandles({ assetId }: AssetCandlesProps) {
  return (
    <section className="flex flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Notowania instrumentu
        </h1>
        <Link
          href="/portfolios"
          className="text-sm text-blue-700 underline underline-offset-2 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-blue-400"
        >
          ← Wróć do portfeli
        </Link>
      </div>

      <CandlePanel
        queryKey={(range: CandleRange) => qk.assetCandles(assetId, range)}
        fetcher={(range: CandleRange) => getAssetCandles(assetId, range)}
      />
    </section>
  );
}
