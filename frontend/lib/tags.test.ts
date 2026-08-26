/**
 * Testy czystych funkcji filtra tagów (`lib/tags.ts`, krok 43).
 *
 * Bez DOM-u i bez sieci — sprawdzamy wyłącznie to, co decyduje o kluczu
 * zapytania: ten sam wybór ma dawać ten sam ciąg niezależnie od kolejności
 * klikania, inaczej TanStack Query trzymałby dwa wpisy na to samo pytanie
 * (i backend dwa wpisy w Redisie).
 */
import { describe, expect, it } from "vitest";

import { parseTagFilter, serializeTagFilter, toggleTag } from "@/lib/tags";

describe("serializeTagFilter", () => {
  it("sortuje i odduplikowuje, żeby ten sam wybór dawał ten sam klucz", () => {
    expect(serializeTagFilter(["REIT", "dywidendowe", "REIT"])).toBe("REIT,dywidendowe");
    expect(serializeTagFilter(["dywidendowe", "REIT"])).toBe("REIT,dywidendowe");
  });

  it("pusty wybór to brak parametru, a nie pusty parametr", () => {
    expect(serializeTagFilter([])).toBeNull();
    expect(serializeTagFilter(["  ", ""])).toBeNull();
  });
});

describe("parseTagFilter", () => {
  it("odtwarza wybór z adresu URL", () => {
    expect(parseTagFilter("REIT,dywidendowe")).toEqual(["REIT", "dywidendowe"]);
  });

  it("brak parametru i pusty parametr znaczą to samo: bez filtra", () => {
    expect(parseTagFilter(null)).toEqual([]);
    expect(parseTagFilter("")).toEqual([]);
    expect(parseTagFilter(",, ,")).toEqual([]);
  });

  it("jest odwrotnością serializeTagFilter", () => {
    const names = ["dywidendowe", "REIT"];
    expect(parseTagFilter(serializeTagFilter(names))).toEqual(["REIT", "dywidendowe"]);
  });
});

describe("toggleTag", () => {
  it("dodaje nieobecny i usuwa obecny", () => {
    expect(toggleTag([], "REIT")).toEqual(["REIT"]);
    expect(toggleTag(["REIT"], "REIT")).toEqual([]);
    expect(toggleTag(["REIT"], "dywidendowe")).toEqual(["REIT", "dywidendowe"]);
  });

  it("nie mutuje wejścia", () => {
    const selected = ["REIT"];
    toggleTag(selected, "dywidendowe");
    expect(selected).toEqual(["REIT"]);
  });
});
