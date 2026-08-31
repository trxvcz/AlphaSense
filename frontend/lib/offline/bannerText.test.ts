import { describe, expect, it } from "vitest";
import { bannerText, dataAgePhrase } from "@/lib/offline/bannerText";

const NOW = new Date("2026-08-30T14:00:00").getTime();
const minutesAgo = (n: number) => NOW - n * 60_000;

describe("bannerText", () => {
  it("milczy, gdy jest sieć — dane odświeżają się same", () => {
    expect(bannerText({ savedAt: minutesAgo(120), isOnline: true }, NOW)).toBeNull();
  });

  it("bez sieci i bez zrzutu mówi wprost, że nie ma czego pokazać", () => {
    expect(bannerText({ savedAt: null, isOnline: false }, NOW)).toBe(
      "Brak połączenia. Nie mamy zapisanych danych do pokazania.",
    );
  });

  it("bez sieci oznacza wiek danych", () => {
    expect(bannerText({ savedAt: minutesAgo(30), isOnline: false }, NOW)).toBe(
      "Brak połączenia — dane sprzed 30 min.",
    );
  });
});

describe("dataAgePhrase", () => {
  it("do dwóch minut to „sprzed chwili”", () => {
    expect(dataAgePhrase(minutesAgo(1), NOW)).toBe("dane sprzed chwili");
  });

  it("poniżej godziny podaje minuty", () => {
    expect(dataAgePhrase(minutesAgo(45), NOW)).toBe("dane sprzed 45 min");
  });

  it("tego samego dnia podaje godzinę", () => {
    expect(dataAgePhrase(minutesAgo(180), NOW)).toBe("dane z godz. 11:00");
  });

  it("po dobie podaje datę i godzinę — sama godzina wprowadzałaby w błąd", () => {
    expect(dataAgePhrase(minutesAgo(60 * 26), NOW)).toBe("dane z 29.08, godz. 12:00");
  });
});
