/**
 * Backend API base. The backend runs on port 8022 (fixed by the project spec).
 *
 * When the console is served BY the backend itself (http://127.0.0.1:8022/ui/
 * or http://127.0.0.1:8022/), use same-origin relative calls — no CORS, no
 * host ambiguity. Otherwise default to localhost:8022 (dev flow) or the
 * build-time NEXT_PUBLIC_API_URL override.
 */
function resolveApiUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (typeof window !== "undefined") {
    const { origin, protocol } = window.location;
    if (protocol === "http:" || protocol === "https:") {
      if (window.location.port === "8022") return ""; // same-origin (backend-served console)
      if (envUrl) return envUrl;
      if (origin.startsWith("http")) return "http://localhost:8022";
    }
    if (protocol === "file:") return envUrl || "http://localhost:8022";
  }
  return envUrl || "http://localhost:8022";
}

export const API_URL = resolveApiUrl();

/**
 * Optional admin token (X-Admin-Token). When the backend runs with
 * ADMIN_AUTH_REQUIRED=1, mutating API calls need the shared token from
 * backend/.env. The owner pastes it once in the console; it is kept in
 * localStorage and sent as a header — never baked into the source.
 */
const ADMIN_TOKEN_KEY = "zr-admin-token";

export function getAdminToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ADMIN_TOKEN_KEY) || "";
}

export function setAdminToken(token: string): void {
  if (typeof window === "undefined") return;
  if (token.trim()) window.localStorage.setItem(ADMIN_TOKEN_KEY, token.trim());
  else window.localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAdminToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { "X-Admin-Token": token } : {}),
      ...(init?.headers || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message = describeError(data, res.status);
    const isLoginCall = path.startsWith("/api/admin/login");
    if (res.status === 401 && !isLoginCall) {
      throw new Error(`${message} — if the console is token-protected, set the admin token (padlock in the header)`);
    }
    throw new Error(message);
  }
  return data as T;
}

/**
 * FastAPI returns `detail` as a string for HTTPException but as an array of
 * validation objects for 422s. Normalise both into one readable message so the
 * console never renders "[object Object]".
 */
function describeError(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        const d = item as { msg?: string; loc?: unknown[] };
        const field = Array.isArray(d.loc) ? d.loc.filter((p) => p !== "body").join(".") : "";
        return field ? `${field}: ${d.msg ?? "invalid"}` : (d.msg ?? "invalid");
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (detail) return JSON.stringify(detail);
  return `HTTP ${status}`;
}
