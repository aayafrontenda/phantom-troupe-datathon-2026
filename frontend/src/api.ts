export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export type Unauthorized = () => void;
let onUnauthorized: Unauthorized | null = null;
export function setUnauthorizedHandler(fn: Unauthorized | null) { onUnauthorized = fn; }

interface Opts {
  method?: string;
  json?: unknown;
  body?: BodyInit;
  headers?: Record<string, string>;
  silent401?: boolean;
}

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers || {}) };
  let body = opts.body;
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, { method: opts.method || 'GET', headers, body, credentials: 'same-origin' });
  let data: unknown = null;
  try { data = await r.json(); } catch {}
  if (!r.ok) {
    if (r.status === 401 && !opts.silent401 && onUnauthorized) onUnauthorized();
    const detail = (data && typeof data === 'object' && 'detail' in data) ? String((data as { detail: unknown }).detail) : `HTTP ${r.status}`;
    throw new ApiError(r.status, detail);
  }
  return data as T;
}

export function wsUrl(path: string): string {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`;
}
