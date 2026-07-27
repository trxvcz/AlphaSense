/**
 * Cienki klient HTTP nad `fetch` — jedyne miejsce, które rozmawia
 * bezpośrednio z API (docs/konwencje.md: „Bez fetch rozsianego po
 * komponentach"). Odpowiada za:
 *
 * - bazowy URL z `NEXT_PUBLIC_API_URL` (fallback do dev API na localhost),
 * - dołożenie `Authorization: Bearer <token>` z `lib/auth/tokenStore.ts`,
 * - parsowanie błędów w formacie kontraktu (`{"error": {code, message,
 *   details}}`, docs/api-kontrakt.md, sekcja „Błędy") na `ApiError`,
 * - silent-refresh: przy 401 na zapytaniu chronionym próbuje RAZ
 *   `POST /auth/refresh` (cookie leci automatycznie, `credentials:
 *   "include"`) i powtarza oryginalne żądanie; jeśli refresh też zawiedzie,
 *   czyści token i przekierowuje na `/login`.
 */

import { getAccessToken, setAccessToken } from "@/lib/auth/tokenStore";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export type ApiErrorBody = {
  error: { code: string; message: string; details: unknown };
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    "message" in error
  );
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Brak treści JSON (np. 204, sieć padła w połowie) — fallback niżej.
  }
  if (isApiErrorBody(body)) {
    return new ApiError(
      response.status,
      body.error.code,
      body.error.message,
      body.error.details,
    );
  }
  return new ApiError(
    response.status,
    "unknown_error",
    `Żądanie nie powiodło się (${response.status}).`,
    null,
  );
}

type RequestOptions = Omit<RequestInit, "body"> & {
  /** Treść żądania — serializowana do JSON. */
  body?: unknown;
  /**
   * Domyślnie `true`: dołącz `Authorization` i obsłuż silent-refresh na
   * 401. Ustaw `false` dla `/auth/login`, `/auth/register` — nie mają
   * jeszcze tokenu, a 401 tam oznacza złe hasło, nie wygasłą sesję.
   */
  auth?: boolean;
};

let refreshInFlight: Promise<boolean> | null = null;

/**
 * Wywołuje `POST /auth/refresh` co najwyżej raz na nakładające się 401
 * (deduplikacja przez `refreshInFlight`) — kilka równoległych zapytań,
 * które dostały 401 w tej samej chwili, dzielą jeden refresh.
 */
export async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = performRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function performRefresh(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) {
      setAccessToken(null);
      return false;
    }
    const data = (await response.json()) as { access_token: string };
    setAccessToken(data.access_token);
    return true;
  } catch {
    setAccessToken(null);
    return false;
  }
}

function redirectToLogin(): void {
  if (typeof window !== "undefined") {
    window.location.assign("/login");
  }
}

async function performRequest<T>(
  path: string,
  options: RequestOptions,
  isRetry: boolean,
): Promise<T> {
  const { auth = true, body, headers, ...rest } = options;

  const finalHeaders = new Headers(headers);
  if (body !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getAccessToken();
    if (token) finalHeaders.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    credentials: "include",
    headers: finalHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (response.status === 401 && auth && !isRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return performRequest<T>(path, options, true);
    }
    redirectToLogin();
    throw await toApiError(response);
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Wykonuje żądanie do API. Rzuca `ApiError` przy odpowiedzi błędu. */
export function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return performRequest<T>(path, options, false);
}
