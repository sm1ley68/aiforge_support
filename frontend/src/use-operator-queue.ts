import { useEffect, useState } from 'react';
import { mockRequests } from './operator-mocks';
import { handoffChanged, handoffKey, readDemoHandoffs } from './store-advisor-demo';
import { demoChatKey, readSupportChats, saveRequestStatus, subscribeToChatChanges } from './request-chat-storage';
import type { OperatorRequest, OperatorStatus } from './operator-types';

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

function demoRequests() {
  return [...readDemoHandoffs(), ...mockRequests];
}

function keyFor(request: OperatorRequest) {
  return demoChatKey(request.id, request.response.conversationId);
}

function changeDemoStatus(request: OperatorRequest, status: OperatorStatus) {
  const lastSeen = request.response.messages.findLast(message => message.role === 'user');
  return saveRequestStatus(keyFor(request), status, lastSeen?.id);
}

export function useOperatorQueue() {
  const [queue, setQueue] = useState<QueueState>(() => isMockQueue
    ? { requests: demoRequests(), status: 'ready' }
    : { requests: [], status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!endpoint) {
      let generation = 0;
      let active = true;
      async function refresh() {
        const current = ++generation;
        const requests = demoRequests();
        const chats = await readSupportChats(requests.map(keyFor)).catch(() => []);
        if (!active || current !== generation) return;
        setQueue({
          requests: requests.map((request, index) => {
            const chat = chats[index];
            if (!chat) return request;
            const clientMessages = chat.customerMessages ?? [];
            const latest = Math.max(Date.parse(request.updatedAt) || 0, chat.workflow?.updatedAt ?? 0, clientMessages.at(-1)?.sentAt ?? 0);
            return {
              ...request,
              status: chat.workflow?.status ?? request.status,
              needsReply: Boolean(chat.workflow?.replyTo),
              updatedAt: latest ? new Date(latest).toISOString() : request.updatedAt,
              handledBy: chat.taken ? 'support' : request.handledBy,
              response: clientMessages.length
                ? { ...request.response, messages: [...request.response.messages, ...clientMessages] }
                : request.response,
            };
          }),
          status: 'ready',
        });
      }
      function onHandoffStorage(event: StorageEvent) {
        if (event.key === handoffKey) void refresh();
      }
      const stopChatUpdates = subscribeToChatChanges(refresh);
      window.addEventListener(handoffChanged, refresh);
      window.addEventListener('storage', onHandoffStorage);
      void refresh();
      return () => {
        active = false;
        stopChatUpdates();
        window.removeEventListener(handoffChanged, refresh);
        window.removeEventListener('storage', onHandoffStorage);
      };
    }
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
    changeStatus: isMockQueue ? changeDemoStatus : undefined,
  };
}
