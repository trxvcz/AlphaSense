/**
 * Tabelaryczna alternatywa dla wykresu alokacji (plan krok 33).
 *
 * Nie jest ozdobą ani „widokiem dla zaawansowanych" — to obowiązkowa
 * alternatywa dla kanwy ECharts, której czytnik ekranu nie przeczyta, i
 * jednocześnie „relief" wymagany przez ostrzeżenie o kontraście palety w
 * trybie jasnym (`lib/chartPalette.ts`). Pokazuje KAŻDY koszyk z osobna, także
 * te, które wykres złożył w „Pozostałe", i kwoty prosto ze stringów z API —
 * bez `Number` po drodze poza samym formatowaniem (`lib/money.ts`).
 */
import type { AllocationBucket, AllocationDimension } from "@/lib/analytics";
import { bucketLabel } from "@/lib/allocationLabels";
import { pln, pct } from "@/lib/money";

type AllocationTableProps = {
  buckets: AllocationBucket[];
  by: AllocationDimension;
};

export function AllocationTable({ buckets, by }: AllocationTableProps) {
  const sorted = [...buckets].sort((a, b) => Number(b.weight) - Number(a.weight));

  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="text-zinc-600 dark:text-zinc-400">
          <th scope="col" className="py-1 pr-2 font-medium">
            Koszyk
          </th>
          <th scope="col" className="py-1 pr-2 text-right font-medium">
            Wartość
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            Udział
          </th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((bucket) => (
          <tr key={bucket.key} className="border-t border-zinc-100 dark:border-zinc-800">
            <th scope="row" className="py-1 pr-2 font-normal">
              {bucketLabel(by, bucket.key)}
            </th>
            <td className="py-1 pr-2 text-right tabular-nums">{pln(bucket.value_pln)}</td>
            <td className="py-1 text-right tabular-nums">{pct(bucket.weight)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
