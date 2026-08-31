/**
 * Testy katalogu komunikatów (plan krok 50, etap 9).
 *
 * Katalog jest teraz jednym miejscem, w którym da się zepsuć **każdy** ekran
 * naraz: pusty tekst albo klucz z literówką nie wywala buildu, tylko wychodzi
 * w interfejsie jako `nav.dashboard`. Te testy to tania siatka pod tym.
 */
import { describe, expect, it } from "vitest";
import messages from "@/messages/pl.json";
import { NAV_ITEMS } from "@/components/nav/navItems";
import { LOCALE, TIME_ZONE } from "@/lib/i18n";

type Catalogue = { [key: string]: string | Catalogue };

function flatten(node: Catalogue, prefix = ""): [string, string][] {
  return Object.entries(node).flatMap(([key, value]) => {
    const path = prefix === "" ? key : `${prefix}.${key}`;
    return typeof value === "string" ? [[path, value] as [string, string]] : flatten(value, path);
  });
}

const entries = flatten(messages as Catalogue);

describe("katalog pl.json", () => {
  it("nie ma pustych komunikatów", () => {
    expect(entries.filter(([, value]) => value.trim() === "")).toEqual([]);
  });

  it("nie zostawia nietkniętego placeholdera bez pary", () => {
    // `{` bez domykającego `}` to najczęstsza literówka w ICU — next-intl
    // rzuci wtedy błędem dopiero przy renderowaniu tego jednego ekranu.
    for (const [path, value] of entries) {
      const open = (value.match(/{/g) ?? []).length;
      const close = (value.match(/}/g) ?? []).length;
      expect(`${path}: ${open}`).toBe(`${path}: ${close}`);
    }
  });
});

it("każda pozycja nawigacji ma etykietę w katalogu", () => {
  for (const item of NAV_ITEMS) {
    expect(Object.keys(messages.nav)).toContain(item.labelKey);
  }
});

it("język i strefa czasowa są ustalone jawnie", () => {
  // Strefa musi być stała, inaczej SSR i przeglądarka sformatują tę samą datę
  // inaczej i użytkownik zobaczy różnicę przy hydratacji.
  expect(LOCALE).toBe("pl");
  expect(TIME_ZONE).toBe("Europe/Warsaw");
});
