import type { Holding } from "@/lib/dashboard";
import { pct, decimal } from "@/lib/money";
import { changeColorClass } from "@/lib/changeColor";
import { hasPriceChange, splitTopMovers, type MovingHolding } from "@/lib/topMovers";

type TopMoversProps = {
  holdings: Holding[];
};

function MoverRow({ holding }: { holding: MovingHolding }) {
  return (
    <li className="flex items-center justify-between gap-3 rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800">
      <span className="font-medium text-zinc-900 dark:text-zinc-50">
        {holding.symbol}
      </span>
      <span className={`text-sm font-semibold ${changeColorClass(holding.price_change_1d.pct)}`}>
        {pct(holding.price_change_1d.pct)}{" "}
        <span className="font-normal text-zinc-500 dark:text-zinc-400">
          ({decimal(holding.price_change_1d.abs)})
        </span>
      </span>
    </li>
  );
}

/**
 * „Top ruchy dnia" (plan krok 32) — zmiana CENY instrumentu d/d
 * (`price_change_1d`, nie zmiana wartości pozycji w PLN, patrz
 * `docs/api-kontrakt.md`). Pozycje bez `price_change_1d` (mniej niż dwa
 * notowania w historii) są pomijane, nie pokazywane jako 0%.
 *
 * Waluta `.abs` jest walutą instrumentu, ale `/holdings` jej dziś nie
 * zwraca (tylko `cost_currency`, czyli walutę ceny zakupu — używanie jej
 * jako etykiety mogłoby wprowadzać w błąd, jeśli różni się od waluty
 * notowania), więc liczba jest pokazana bez symbolu waluty.
 */
export function TopMovers({ holdings }: TopMoversProps) {
  const withChange = holdings.filter(hasPriceChange);

  if (withChange.length === 0) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Brak danych o zmianach cen na dziś (za mało notowań w historii).
      </p>
    );
  }

  const { gainers, losers } = splitTopMovers(holdings);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          Największe wzrosty
        </h3>
        {gainers.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Brak wzrostów dziś.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {gainers.map((holding) => (
              <MoverRow key={holding.id} holding={holding} />
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          Największe spadki
        </h3>
        {losers.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Brak spadków dziś.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {losers.map((holding) => (
              <MoverRow key={holding.id} holding={holding} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
