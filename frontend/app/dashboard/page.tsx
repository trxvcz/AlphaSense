/**
 * `/dashboard` z nawigacji — dashboard żyje pod KONKRETNYM portfelem
 * (`/portfolios/{id}`), a nawigacja globalna żadnego nie zna, więc ta trasa
 * tylko wybiera portfel i przekazuje dalej. Dokładnie ten sam wzorzec co
 * `/struktura` (krok 33) i `/rynki` (krok 34) — `PortfolioPicker` z pustym
 * `section`.
 *
 * Do kroku 35 `/dashboard` był w `NAV_ITEMS` linkiem placeholder i prowadził
 * na 404 (backlog etapu 6). Alternatywą było usunięcie pozycji z nawigacji,
 * ale „Dashboard" jest w niej pierwszym i najbardziej oczekiwanym wejściem —
 * taniej i mniej myląco jest sprawić, żeby działało, niż tłumaczyć, czemu
 * go nie ma.
 */
import { PortfolioPicker } from "@/components/portfolio/PortfolioPicker";

export default function DashboardPage() {
  return (
    <PortfolioPicker
      section=""
      title="Dashboard"
      description="Wybierz portfel, którego dashboard chcesz zobaczyć."
      emptyDescription="Dashboard pokazuje wartość portfela, wykres i top ruchy dnia — najpierw utwórz portfel i dodaj do niego pozycje."
    />
  );
}
