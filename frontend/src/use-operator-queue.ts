import { useEffect, useState } from 'react';
import type { OperatorRequest } from './operator-types';
import type { AgentResponse } from './agent-types';
import { ApiError, json, requestsUrl } from './softline-api';

type QueueState = {
  requests: OperatorRequest[];
  status: 'loading' | 'ready' | 'error' | 'unauthorized';
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
  type ServerRequest = Omit<OperatorRequest, 'response'> & {
    response: Omit<AgentResponse, 'messages'> & {
      messages: (AgentResponse['messages'][number] & { author?: 'manager' })[];
    };
  };
  const data = await json<ServerRequest[]>(url, { signal });
  if (!isRequestList(data)) throw new TypeError('Invalid request list');
  return data.map(row => ({
    ...row,
    response: {
      ...row.response,
      messages: row.response.messages.map(message => message.author === 'manager'
        ? { ...message, role: 'support' as const } : message),
    },
  }));
}

export function useOperatorQueue() {
  const [queue, setQueue] = useState<QueueState>({ requests: [], status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    let running = false;
    let needsSignIn = false;

    async function load() {
      if (running || controller.signal.aborted) return;
      running = true;
      window.clearTimeout(timer);
      try {
        const requests = await fetchRequests(requestsUrl, controller.signal);
        if (!controller.signal.aborted) setQueue(current => current.status === 'ready' &&
          JSON.stringify(current.requests) === JSON.stringify(requests) ? current : { requests, status: 'ready' });
      } catch (error) {
        needsSignIn = error instanceof ApiError && error.status === 401;
        if (!controller.signal.aborted) setQueue(current => needsSignIn
          ? { requests: [], status: 'unauthorized' }
          : { ...current, status: 'error' });
      } finally {
        running = false;
        if (!controller.signal.aborted && !needsSignIn) timer = window.setTimeout(load, document.hidden ? 5000 : 1500);
      }
    }

    void load();
    window.addEventListener('focus', load);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      window.removeEventListener('focus', load);
    };
  }, [attempt]);

  return {
    requests: queue.requests,
    loading: queue.status === 'loading',
    error: queue.status === 'error' ? 'Не удалось загрузить журнал запросов.' : '',
    reload: () => setAttempt(current => current + 1),
    unauthorized: queue.status === 'unauthorized',
  };
}
