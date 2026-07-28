/**
 * `/rynki` z nawigacji (plan krok 34) — ranking rynków dotyczy konkretnego
 * portfela, a nawigacja nie zna żadnego, więc ta trasa tylko wybiera portfel
 * i przekazuje dalej do `/portfolios/{id}/rynki`. Cała logika wyboru jest w
 * `PortfolioPicker` (dzielona z `/struktura`).
 */
import { PortfolioPicker } from "@/components/portfolio/PortfolioPicker";

export default function RynkiPage() {
  return (
    <PortfolioPicker
      section="rynki"
      title="Twoje rynki"
      description="Wybierz portfel, dla którego chcesz zobaczyć ranking rynków."
      emptyDescription="Ranking rynków pokazuje, gdzie stoją Twoje pieniądze — najpierw utwórz portfel i dodaj do niego pozycje."
    />
  );
}
