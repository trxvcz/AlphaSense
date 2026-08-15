/**
 * `/newsy` z nawigacji (plan krok 46) — feed dotyczy konkretnego portfela
 * (pokazuje newsy o pozycjach, które użytkownik trzyma), a nawigacja nie zna
 * żadnego, więc ta trasa tylko wybiera portfel i przekazuje dalej do
 * `/portfolios/{id}/newsy`. Cała logika wyboru jest w `PortfolioPicker`
 * (dzielona z `/struktura` i `/rynki`).
 */
import { PortfolioPicker } from "@/components/portfolio/PortfolioPicker";

export default function NewsyPage() {
  return (
    <PortfolioPicker
      section="newsy"
      title="Newsy"
      description="Wybierz portfel, dla którego chcesz zobaczyć newsy."
      emptyDescription="Feed pokazuje newsy o pozycjach, które trzymasz — najpierw utwórz portfel i dodaj do niego pozycje."
    />
  );
}
