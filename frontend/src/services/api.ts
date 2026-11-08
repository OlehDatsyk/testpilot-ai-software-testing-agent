/**
 * Thin typed client for the TestPilot REST API.
 * Only the user's own access token is stored in the browser — never GitHub or AI credentials.
 */
const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') || 'http://localhost:8000';
const TOKEN_KEY = 'testpilot.token';

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: unknown) {
    super(message);
  }
}

export const tokenStore = {
  get: (): string | null => {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ } },
};

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

type Query = Record<string, string | number | boolean | null | undefined>;

function url(path: string, query?: Query): string {
  const u = new URL(BASE + path);
  if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') u.searchParams.set(k, String(v));
  return u.toString();
}

async function request<T>(method: string, path: string, opts: { body?: unknown; query?: Query; form?: FormData; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body); }
  let res: Response;
  try {
    res = await fetch(url(path, opts.query), { method, headers, body });
  } catch {
    throw new ApiError(0, `Cannot reach the TestPilot API at ${BASE}. Is the backend running?`);
  }
  if (res.status === 401 && token) onUnauthorized?.();
  if (!res.ok) {
    let message = res.statusText || 'Request failed';
    let details: unknown;
    try {
      const j = await res.json();
      message = j?.error?.message ?? j?.detail ?? message;
      details = j?.error?.details;
      if (Array.isArray(details) && details.length) {
        message += ': ' + details.map((d: { field?: string; message?: string }) => `${d.field ? d.field + ' — ' : ''}${d.message ?? ''}`).join('; ');
      }
    } catch { /* non-JSON error */ }
    throw new ApiError(res.status, typeof message === 'string' ? message : 'Request failed', details);
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type') || '';
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  base: BASE,
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body: body ?? {}, query }),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
  del: <T = void>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, { form }),
  /** Authenticated file download (reports, exports). */
  async download(path: string, filename: string, query?: Query) {
    const res = await request<Response>('GET', path, { query, raw: true });
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  },
  /** Open an authenticated HTML/PDF in a new tab. */
  async open(path: string, query?: Query) {
    const res = await request<Response>('GET', path, { query, raw: true });
    const blob = await res.blob();
    window.open(URL.createObjectURL(blob), '_blank', 'noopener');
  },
};
