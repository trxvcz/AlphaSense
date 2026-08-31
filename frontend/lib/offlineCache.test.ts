/**
 * Testy trwałego cache'u (plan krok 49, etap 9).
 *
 * Sedno nie jest w zapisie, tylko w **izolacji**: zrzut z dysku nie może
 * wjechać do sesji innego użytkownika na tym samym urządzeniu
 * (CLAUDE.md #3.2/#3.10). Dlatego testy pilnują odczytu, nie wydajności.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const store = new Map<string, unknown>();

vi.mock("idb-keyval", () => ({
  get: async (key: string) => store.get(key),
  set: async (key: string, value: unknown) => {
    store.set(key, value);
  },
  del: async (key: string) => {
    store.delete(key);
  },
}));

const {
  MAX_CACHE_AGE_MS,
  cacheOwner,
  clearPersistedCache,
  loadPersistedCache,
  savePersistedCache,
} = await import("./offlineCache");

/** Token bez podpisu — `cacheOwner` czyta wyłącznie `sub`, nie weryfikuje. */
function token(sub: string): string {
  const payload = btoa(JSON.stringify({ sub })).replace(/\+/g, "-").replace(/\//g, "_");
  return `header.${payload}.signature`;
}

const state = { mutations: [], queries: [] };

beforeEach(() => {
  store.clear();
});

describe("cacheOwner", () => {
  it("czyta sub z tokenu", () => {
    expect(cacheOwner(token("user-a"))).toBe("user-a");
  });

  it.each([
    ["brak tokenu", null],
    ["śmieć zamiast tokenu", "to-nie-jest-jwt"],
    ["payload bez sub", `header.${btoa(JSON.stringify({ email: "x@example.com" }))}.sig`],
  ])("zwraca null: %s", (_opis, value) => {
    expect(cacheOwner(value)).toBeNull();
  });
});

describe("loadPersistedCache", () => {
  it("wczytuje zrzut właściciela", async () => {
    await savePersistedCache({ owner: "user-a", savedAt: 1_000, state });

    const loaded = await loadPersistedCache("user-a", 2_000);

    expect(loaded?.savedAt).toBe(1_000);
  });

  it("NIE wczytuje cudzego zrzutu", async () => {
    await savePersistedCache({ owner: "user-a", savedAt: 1_000, state });

    expect(await loadPersistedCache("user-b", 2_000)).toBeNull();
  });

  it("bez sesji nie wczytuje niczego", async () => {
    await savePersistedCache({ owner: "user-a", savedAt: 1_000, state });

    expect(await loadPersistedCache(null, 2_000)).toBeNull();
  });

  it("odrzuca zrzut starszy niż limit", async () => {
    await savePersistedCache({ owner: "user-a", savedAt: 0, state });

    expect(await loadPersistedCache("user-a", MAX_CACHE_AGE_MS + 1)).toBeNull();
    expect(await loadPersistedCache("user-a", MAX_CACHE_AGE_MS)).not.toBeNull();
  });
});

it("wylogowanie kasuje zrzut niezależnie od właściciela", async () => {
  await savePersistedCache({ owner: "user-a", savedAt: 1_000, state });

  await clearPersistedCache();

  expect(await loadPersistedCache("user-a", 2_000)).toBeNull();
});
