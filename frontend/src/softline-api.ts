import type { Source } from './agent-types';

export const requestsUrl = import.meta.env.VITE_AGENT_REQUESTS_URL?.trim() || '/api/requests';

export type ChatSession = { chat_id: string; chat_token: string };
export type ChatMessage = { turn_id: string; role: 'user' | 'assistant'; text: string; author?: 'manager'; client_message_id?: string };
export type QuoteCustomer = { company: string; inn: string; kpp: string };
export type Quote = {
  offer_id: string; title: string; sku?: string | null; quantity: number; unit_label: string;
  unit_price: string; total: string; currency: string;
  catalog_snapshot_at: string; issued_at: string; source: Source;
  customer?: QuoteCustomer | null; delivery_status: 'available' | 'requires_confirmation';
  price_origin_label: string; vat_label?: string | null;
};
export type CatalogCard = {
  offer_id: string; sku?: string | null; title: string; url: string; snapshot_at: string;
  match_summary: string; price_amount?: string | null; currency?: string | null; availability?: boolean | null;
  verified_facts: { field: string; value: string; source: Source }[];
};
export type Availability = {
  status: 'working_hours' | 'outside_working_hours' | 'unknown'; message: string; email?: string;
  schedule?: { start: string; end: string; weekdays: number[]; timezone: string };
};
export type HandoffState = { status: 'review' | 'waiting' | 'resolved'; hasContact: boolean; support: Availability };
export type Turn = {
  turn_id: string; status: 'queued' | 'processing' | 'succeeded' | 'failed';
  outcome?: 'answer' | 'clarify' | 'recommend' | 'handoff' | null;
  text?: string | null; products: CatalogCard[]; sources: Source[]; quote?: Quote | null; support?: Availability | null; from_manager_knowledge?: boolean;
};

export class ApiError extends Error {
  constructor(readonly status: number, readonly detail?: string) {
    super(detail || `HTTP ${status}`);
  }
}

export async function api(path: string, { signal, ...init }: RequestInit = {}) {
  const timeout = AbortSignal.timeout(8000);
  const headers = new Headers(init.headers);
  if (init.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, {
    ...init, headers, cache: 'no-store', signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => undefined);
    throw new ApiError(response.status, typeof body?.detail === 'string' ? body.detail : undefined);
  }
  return response;
}

export async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await api(path, init)).json();
}

export function chatRequest(session: ChatSession, init: RequestInit = {}): RequestInit {
  return { ...init, headers: { Authorization: `Bearer ${session.chat_token}` } };
}

export const chatPath = (session: ChatSession) => `/chats/${session.chat_id}`;
export const turnPath = (session: ChatSession, turnId: string) => `${chatPath(session)}/turns/${turnId}`;

export function safeLink(value: string) {
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' || url.protocol === 'http:') return url.href;
  } catch { /* Ignore malformed source URLs. */ }
}

export function formatCatalogDate(date: string) {
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'long', timeZone: 'Europe/Moscow' }).format(new Date(date));
}

export function formatPrice(price: string, currency: string) {
  const amount = Number(price);
  if (!Number.isFinite(amount)) return `${price} ${currency}`;
  try {
    return new Intl.NumberFormat('ru-RU', { style: 'currency', currency, minimumFractionDigits: Number.isInteger(amount) ? 0 : 2 }).format(amount);
  } catch {
    return `${price} ${currency}`;
  }
}
