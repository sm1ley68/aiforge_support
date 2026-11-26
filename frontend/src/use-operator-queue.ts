import { useEffect, useState } from 'react';
import { mockRequests } from './operator-mocks';
import type { OperatorRequest } from './operator-types';

const endpoint = import.meta.env.VITE_AGENT_REQUESTS_URL?.trim();
export const isMockQueue = !endpoint;

type QueueState = {
  requests: OperatorRequest[];
  status: 'loading' | 'ready' | 'error';
};

function isRequestList(data: unknown): data is OperatorRequest[] {
  return Array.isArray(data) && data.every(item =>
    typeof item?.id === 'string' && typeof item.title === 'string' && typeof item.customer === 'string' &&
    typeof item.updatedAt === 'string' && ['review', 'waiting', 'resolved'].includes(item.status) &&
    Array.isArray(item.response?.messages) && Array.isArray(item.response.products) &&
    Array.isArray(item.response.requirements) && Array.isArray(item.response.sources) && Array.isArray(item.response.trace),
  );
}

async function fetchRequests(url: string, signal: AbortSignal) {
  const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`Queue request failed (HTTP ${response.status})`);

  const data: unknown = await response.json();
  if (!isRequestList(data)) throw new TypeError('Invalid request list');
  return data;
}

export function useOperatorQueue() {
  const [queue, setQueue] = useState<QueueState>(() => isMockQueue
    ? { requests: mockRequests, status: 'ready' }
    : { requests: [], status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!endpoint) return;
    const controller = new AbortController();

    async function load(url: string) {
      setQueue(current => ({ ...current, status: 'loading' }));
      try {
        const requests = await fetchRequests(url, controller.signal);
        if (!controller.signal.aborted) setQueue({ requests, status: 'ready' });
      } catch {
        if (!controller.signal.aborted) setQueue(current => ({ ...current, status: 'error' }));
      }
    }

    void load(endpoint);
    return () => controller.abort();
  }, [attempt]);

  return {
    requests: queue.requests,
    loading: queue.status === 'loading',
    error: queue.status === 'error' ? 'Не удалось загрузить журнал запросов.' : '',
    reload: () => setAttempt(current => current + 1),
  };
}
