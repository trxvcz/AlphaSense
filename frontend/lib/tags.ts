/**
 * Dostęp do tagów użytkownika (`/tags`, krok 43, etap 8) — jedyne miejsce,
 * które woła `apiFetch` dla tego zasobu (docs/konwencje.md: „Bez fetch
 * rozsianego po komponentach").
 *
 * Kształty 1:1 z `docs/api-kontrakt.md` i `tags/schemas.py`.
 *
 * Tag wisi na **aktywie**, nie na pozycji — „dywidendowe" to cecha spółki,
 * więc etykieta działa we wszystkich portfelach użytkownika. Stąd trasy
 * `/tags/{tag_id}/assets/{asset_id}`, a nie `/holdings/...`.
 *
 * Poza wywołaniami siedzą tu **czyste funkcje** opisujące filtr
 * (`serializeTagFilter`, `parseTagFilter`, `toggleTag`), testowane bez DOM-u
 * w `lib/tags.test.ts` — wzorzec `lib/news.ts` + `lib/news.test.ts`.
 */
import { apiFetch } from "@/lib/api";

export type Tag = {
  id: string;
  name: string;
  /** `#rrggbb` albo `null`. NIGDY jedyny nośnik informacji — obok zawsze nazwa. */
  color: string | null;
  created_at: string;
  /** Liczba aktywów otagowanych przez TEGO użytkownika. */
  asset_count: number;
};

export type TaggedAsset = {
  id: string;
  symbol: string;
  name: string;
  market_code: string;
  currency: string;
};

export function getTags(): Promise<Tag[]> {
  return apiFetch<Tag[]>("/tags");
}

export function createTag(input: { name: string; color?: string | null }): Promise<Tag> {
  const body: { name: string; color?: string } = { name: input.name };
  if (input.color) body.color = input.color;
  return apiFetch<Tag>("/tags", { method: "POST", body });
}

export function deleteTag(tagId: string): Promise<void> {
  return apiFetch<void>(`/tags/${tagId}`, { method: "DELETE" });
}

export function getTagAssets(tagId: string): Promise<TaggedAsset[]> {
  return apiFetch<TaggedAsset[]>(`/tags/${tagId}/assets`);
}

/** Idempotentne — powtórne otagowanie tego samego aktywa nie jest błędem. */
export function attachTag(tagId: string, assetId: string): Promise<void> {
  return apiFetch<void>(`/tags/${tagId}/assets/${assetId}`, { method: "PUT" });
}

/** 204 także wtedy, gdy powiązania nie było — stan końcowy jest ten sam. */
export function detachTag(tagId: string, assetId: string): Promise<void> {
  return apiFetch<void>(`/tags/${tagId}/assets/${assetId}`, { method: "DELETE" });
}

/**
 * Nazwy tagów → wartość parametru `?tags=`. Sortowanie i odduplikowanie robimy
 * po stronie klienta, żeby ten sam wybór dawał ten sam klucz TanStack Query
 * (i ten sam klucz cache po stronie API) niezależnie od kolejności klikania.
 *
 * Pusty wybór → `null`, czyli **brak parametru**, a nie `?tags=` — puste
 * `tags` backend traktuje jak brak filtra, ale nie ma powodu wysyłać śmieci.
 */
export function serializeTagFilter(names: readonly string[]): string | null {
  const unique = Array.from(new Set(names.map((n) => n.trim()).filter(Boolean))).sort();
  return unique.length > 0 ? unique.join(",") : null;
}

/** Odwrotność `serializeTagFilter` — do odtworzenia wyboru z adresu URL. */
export function parseTagFilter(raw: string | null): string[] {
  if (!raw) return [];
  return Array.from(new Set(raw.split(",").map((n) => n.trim()).filter(Boolean))).sort();
}

/** Przełącza obecność nazwy w wyborze (klik w chip filtra). */
export function toggleTag(selected: readonly string[], name: string): string[] {
  return selected.includes(name)
    ? selected.filter((n) => n !== name)
    : [...selected, name].sort();
}
