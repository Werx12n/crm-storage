// Клієнт API: JWT, повідомлення про помилки українською і офлайн-черга ТЗД (NFR-2.3).

export type User = { id: number; login: string; full_name: string; roles: string[] };

const TOKEN_KEY = "wms.token";
const USER_KEY = "wms.user";
const QUEUE_KEY = "wms.queue";
const ERRORS_KEY = "wms.queue.errors";

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return store()?.getItem(TOKEN_KEY) ?? null;
}

export function getUser(): User | null {
  try {
    const raw = store()?.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: User) {
  store()?.setItem(TOKEN_KEY, token);
  store()?.setItem(USER_KEY, JSON.stringify(user));
}

export function logout() {
  store()?.removeItem(TOKEN_KEY);
  store()?.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  code?: string;
  data: any;
  constructor(status: number, message: string, data: any) {
    super(message);
    this.status = status;
    this.code = data?.code;
    this.data = data;
  }
}

function headers(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json", ...(extra ?? {}) };
  const t = getToken();
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

async function handle(r: Response) {
  if (r.status === 401 && getToken()) {
    logout();
    if (!location.pathname.startsWith("/login")) location.href = "/login";
  }
  const ct = r.headers.get("content-type") ?? "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    let msg = typeof data === "object" && data?.detail ? data.detail : `Помилка ${r.status}`;
    if (Array.isArray(msg)) msg = msg.map((d: any) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join("; ");
    throw new ApiError(r.status, String(msg), data);
  }
  return data;
}

export async function get<T = any>(url: string): Promise<T> {
  return handle(await fetch(url, { headers: headers() }));
}

export async function post<T = any>(url: string, body?: unknown, extra?: Record<string, string>): Promise<T> {
  return handle(await fetch(url, { method: "POST", headers: headers(extra), body: JSON.stringify(body ?? {}) }));
}

export async function put<T = any>(url: string, body?: unknown): Promise<T> {
  return handle(await fetch(url, { method: "PUT", headers: headers(), body: JSON.stringify(body ?? {}) }));
}

export async function download(url: string, body?: unknown): Promise<string> {
  const r = await fetch(url, {
    method: body ? "POST" : "GET",
    headers: headers(),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) await handle(r);
  return URL.createObjectURL(await r.blob());
}

// ---------- Офлайн-черга ТЗД ----------
export type QueuedOp = { id: string; url: string; body: unknown; label: string; at: string };

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export function queue(): QueuedOp[] {
  try {
    return JSON.parse(store()?.getItem(QUEUE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function queueErrors(): string[] {
  try {
    return JSON.parse(store()?.getItem(ERRORS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function saveQueue(q: QueuedOp[]) {
  store()?.setItem(QUEUE_KEY, JSON.stringify(q));
  window.dispatchEvent(new Event("wms-queue"));
}

export function clearQueueErrors() {
  store()?.removeItem(ERRORS_KEY);
  window.dispatchEvent(new Event("wms-queue"));
}

/** POST, що працює і без зв'язку: при відсутності мережі операція ставиться в чергу з ключем ідемпотентності. */
export async function postOffline<T = any>(url: string, body: unknown, label: string): Promise<T | { queued: true }> {
  const op: QueuedOp = { id: uuid(), url, body, label, at: new Date().toISOString() };
  if (!navigator.onLine) {
    saveQueue([...queue(), op]);
    return { queued: true };
  }
  try {
    return await post<T>(url, body, { "Idempotency-Key": op.id });
  } catch (e) {
    if (e instanceof ApiError) throw e;
    saveQueue([...queue(), op]); // мережева помилка — у чергу
    return { queued: true };
  }
}

let syncing = false;

export async function syncQueue(): Promise<{ sent: number; failed: number }> {
  if (syncing || !navigator.onLine) return { sent: 0, failed: 0 };
  syncing = true;
  let sent = 0;
  let failed = 0;
  try {
    for (const op of queue()) {
      try {
        await post(op.url, op.body, { "Idempotency-Key": op.id });
        sent++;
      } catch (e) {
        if (!(e instanceof ApiError)) break; // знову немає зв'язку — повторимо пізніше
        failed++;
        const errs = [...queueErrors(), `${op.label}: ${e.message}`];
        store()?.setItem(ERRORS_KEY, JSON.stringify(errs.slice(-20)));
      }
      saveQueue(queue().filter((x) => x.id !== op.id));
    }
  } finally {
    syncing = false;
  }
  return { sent, failed };
}

export function isQueued(x: unknown): x is { queued: true } {
  return typeof x === "object" && x !== null && (x as any).queued === true;
}
