/**
 * `/struktura` z nawigacji (plan krok 33) — struktura dotyczy konkretnego
 * portfela, a nawigacja nie zna żadnego, więc ta trasa tylko wybiera portfel
 * i przekazuje dalej do `/portfolios/{id}/struktura`, gdzie żyje właściwy
 * widok. Cała logika wyboru jest w `PortfolioPicker` (dzielona z `/rynki`).
 */
import { PortfolioPicker } from "@/components/portfolio/PortfolioPicker";

export default function StrukturaPage() {
  return (
    <PortfolioPicker
      section="struktura"
      title="Struktura portfela"
      description="Wybierz portfel, którego skład chcesz zobaczyć."
      emptyDescription="Struktura pokazuje skład portfela — najpierw utwórz portfel i dodaj do niego pozycje."
    />
  );
}
