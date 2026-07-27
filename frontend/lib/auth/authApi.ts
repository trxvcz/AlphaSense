/**
 * Wywołania `/auth/*`, które nie przechodzą przez standardową logikę
 * silent-refresh `apiFetch` (nie mają jeszcze tokenu albo go właśnie
 * unieważniają) — `auth: false` pomija dołożenie nagłówka `Authorization`
 * i próbę odświeżenia na 401.
 */
import { apiFetch } from "@/lib/api";

export type LoginResponse = {
  access_token: string;
  token_type: string;
};

export type RegisterResponse = {
  id: string;
  email: string;
  created_at: string;
};

export function loginRequest(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
    auth: false,
  });
}

export function registerRequest(email: string, password: string): Promise<RegisterResponse> {
  return apiFetch<RegisterResponse>("/auth/register", {
    method: "POST",
    body: { email, password },
    auth: false,
  });
}

export function logoutRequest(): Promise<void> {
  return apiFetch<void>("/auth/logout", { method: "POST", auth: false });
}
