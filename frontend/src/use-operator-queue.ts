import { useEffect, useState } from 'react';
import { mockRequests } from './operator-mocks';
import type { OperatorRequest } from './operator-types';

const endpoint = import.meta.env.VITE_AGENT_REQUESTS_URL?.trim();
export const isMockQueue = !endpoint;

function isRequestList(data: unknown): data is OperatorRequest[] {
  return Array.isArray(data) && data.every(item =>
    typeof item?.id === 'string' && typeof item.title === 'string' && typeof item.customer === 'string' &&
    typeof item.updatedAt === 'string' && ['review', 'waiting', 'resolved'].includes(item.status) &&
    Array.isArray(item.response?.messages) && Array.isArray(item.response.products) &&
    Array.isArray(item.response.requirements) && Array.isArray(item.response.sources) && Array.isArray(item.response.trace),
  );
}

export function useOperatorQueue() {
  const [requests, setRequests] = useState<OperatorRequest[]>(isMockQueue ? mockRequests : []);
  const [loading, setLoading] = useState(!isMockQueue);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!endpoint) return;
    const controller = new AbortController();

    async function load(url: string) {
      setLoading(true);
      setError('');
      try {
        const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(`Queue request failed (HTTP ${response.status})`);
        const data: unknown = await response.json();
        if (!isRequestList(data)) throw new TypeError('Invalid request list');
        if (!controller.signal.aborted) setRequests(data);
      } catch {
        if (!controller.signal.aborted) setError('Не удалось загрузить журнал запросов.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    void load(endpoint);
    return () => controller.abort();
  }, [attempt]);

  return {
    requests, loading, error,
    reload: () => setAttempt(current => current + 1),
  };
}
