/**
 * Testy logiki banera offline. Od kroku 50 funkcje zwracają **klucz
 * komunikatu i parametry**, nie gotowe zdanie — treść mieszka w
 * `messages/pl.json`. Ostatni test pilnuje styku obu światów: każdy klucz,
 * który ta logika potrafi zwrócić, musi istnieć w katalogu.
 */
import { describe, expect, it } from "vitest";
import { bannerMessage, dataAgeMessage } from "@/lib/offline/bannerText";
import messages from "@/messages/pl.json";

const NOW = new Date("2026-08-30T14:00:00").getTime();
const minutesAgo = (n: number) => NOW - n * 60_000;

describe("bannerMessage", () => {
  it("milczy, gdy jest sieć — dane odświeżają się same", () => {
    expect(bannerMessage({ savedAt: minutesAgo(120), isOnline: true }, NOW)).toBeNull();
  });

  it("bez sieci i bez zrzutu mówi wprost, że nie ma czego pokazać", () => {
    expect(bannerMessage({ savedAt: null, isOnline: false }, NOW)).toEqual({ key: "noData" });
  });

  it("bez sieci oznacza wiek danych", () => {
    expect(bannerMessage({ savedAt: minutesAgo(30), isOnline: false }, NOW)).toEqual({
      key: "withAge",
      age: { key: "ageMinutes", values: { minutes: 30 } },
    });
  });
});

describe("dataAgeMessage", () => {
  it("do dwóch minut to „sprzed chwili”", () => {
    expect(dataAgeMessage(minutesAgo(1), NOW)).toEqual({ key: "ageJustNow" });
  });

  it("poniżej godziny podaje minuty", () => {
    expect(dataAgeMessage(minutesAgo(45), NOW)).toEqual({
      key: "ageMinutes",
      values: { minutes: 45 },
    });
  });

  it("tego samego dnia podaje godzinę", () => {
    expect(dataAgeMessage(minutesAgo(180), NOW)).toEqual({
      key: "ageToday",
      values: { time: "11:00" },
    });
  });

  it("po dobie podaje datę i godzinę — sama godzina wprowadzałaby w błąd", () => {
    expect(dataAgeMessage(minutesAgo(60 * 26), NOW)).toEqual({
      key: "ageOlder",
      values: { date: "29.08", time: "12:00" },
    });
  });
});

it("każdy klucz banera istnieje w katalogu komunikatów", () => {
  const used = [
    bannerMessage({ savedAt: null, isOnline: false }, NOW),
    bannerMessage({ savedAt: minutesAgo(1), isOnline: false }, NOW),
    bannerMessage({ savedAt: minutesAgo(45), isOnline: false }, NOW),
    bannerMessage({ savedAt: minutesAgo(180), isOnline: false }, NOW),
    bannerMessage({ savedAt: minutesAgo(60 * 26), isOnline: false }, NOW),
  ];

  const keys = used.flatMap((message) =>
    message === null ? [] : message.key === "withAge" ? [message.key, message.age.key] : [message.key],
  );

  for (const key of keys) {
    expect(Object.keys(messages.offline.banner)).toContain(key);
  }
});
