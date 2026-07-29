/**
 * Etykiety i składanie koszyków alokacji (`lib/allocationLabels.ts`, krok 33).
 *
 * Dwie rzeczy, które naprawdę mogą się zepsuć po cichu: nieznany klucz z
 * bazy (nowy sektor dodany przez dostawcę metadanych) i przycięcie koszyków
 * do liczby slotów palety — zapętlenie palety dałoby DWA różne koszyki w tym
 * samym kolorze, czyli wykres kłamiący, nie brzydki.
 */
import { describe, expect, it } from "vitest";

import { bucketLabel, toChartSlices } from "@/lib/allocationLabels";
import type { AllocationBucket } from "@/lib/analytics";

function bucket(key: string, weight: string, valuePln = "100"): AllocationBucket {
  return { key, weight, value_pln: valuePln };
}

describe("bucketLabel", () => {
  it("tłumaczy znane klasy i sektory na polski", () => {
    expect(bucketLabel("class", "equity")).toBe("Akcje");
    expect(bucketLabel("sector", "technology")).toBe("Technologia");
  });

  it("nieznany klucz pokazuje w oryginale z wielkiej litery, nie gubi koszyka", () => {
    expect(bucketLabel("sector", "biotechnologia")).toBe("Biotechnologia");
    expect(bucketLabel("class", "warrant")).toBe("Warrant");
  });

  it("koszyk zbiorczy backendu ma polską etykietę w każdym wymiarze", () => {
    expect(bucketLabel("class", "nieznane")).toBe("Nieznane");
    expect(bucketLabel("geo", "nieznane")).toBe("Nieznane");
  });

  it("geografii i waluty nie tłumaczy — są już po polsku albo międzynarodowe", () => {
    expect(bucketLabel("geo", "Polska")).toBe("Polska");
    expect(bucketLabel("currency", "USD")).toBe("USD");
  });
});

describe("toChartSlices", () => {
  it("sortuje malejąco po wadze, niezależnie od kolejności z API", () => {
    const slices = toChartSlices(
      [bucket("a", "0.2"), bucket("b", "0.5"), bucket("c", "0.3")],
      "currency",
    );

    expect(slices.map((s) => s.label)).toEqual(["b", "c", "a"]);
    expect(slices.every((s) => !s.isOther)).toBe(true);
  });

  it("nie składa niczego, gdy koszyków jest dokładnie tyle co slotów", () => {
    const buckets = [bucket("a", "0.5"), bucket("b", "0.3"), bucket("c", "0.2")];

    const slices = toChartSlices(buckets, "currency", 3);

    expect(slices).toHaveLength(3);
    expect(slices.some((s) => s.isOther)).toBe(false);
  });

  it("nadmiar ponad liczbę slotów składa w jedno „Pozostałe”", () => {
    const buckets = [
      bucket("a", "0.4", "400"),
      bucket("b", "0.3", "300"),
      bucket("c", "0.2", "200"),
      bucket("d", "0.07", "70"),
      bucket("e", "0.03", "30"),
    ];

    const slices = toChartSlices(buckets, "currency", 3);

    // 3 sloty = 2 największe koszyki + jeden zbiorczy, nigdy 3 + zbiorczy.
    expect(slices).toHaveLength(3);
    expect(slices.slice(0, 2).map((s) => s.label)).toEqual(["a", "b"]);

    const other = slices[2];
    expect(other.isOther).toBe(true);
    expect(other.label).toBe("Pozostałe (3)");
    expect(other.value).toBeCloseTo(300, 8); // 200 + 70 + 30
    expect(other.weight).toBeCloseTo(0.3, 8); // 0.2 + 0.07 + 0.03
  });

  it("suma wag po złożeniu nadal daje 1 — wykres nie gubi części portfela", () => {
    const buckets = [
      bucket("a", "0.4"),
      bucket("b", "0.3"),
      bucket("c", "0.2"),
      bucket("d", "0.1"),
    ];

    const total = toChartSlices(buckets, "currency", 2).reduce((sum, s) => sum + s.weight, 0);

    expect(total).toBeCloseTo(1, 8);
  });

  it("pusta lista koszyków daje pustą listę wycinków, nie wyjątek", () => {
    expect(toChartSlices([], "class")).toEqual([]);
  });

  it("tłumaczy etykiety wycinków tym samym wymiarem, który dostaje", () => {
    const slices = toChartSlices([bucket("equity", "1")], "class");

    expect(slices[0].label).toBe("Akcje");
  });
});
