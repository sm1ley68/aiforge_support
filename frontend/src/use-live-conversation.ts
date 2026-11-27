import { useEffect, useRef, useState } from 'react';
import { ApiError, chatPath, chatRequest, json, turnPath } from './softline-api';
import type { ChatMessage, ChatSession, HandoffState, Turn } from './softline-api';

type Pending = { id: string; text: string; manager?: boolean; turnId?: string };
type SavedChat = { session?: ChatSession; pending?: Pending };
const storageKey = 'softline.live-chat.v1';

function restore(): SavedChat {
  try {
    return JSON.parse(sessionStorage.getItem(storageKey) || '{}');
  } catch {
    return {};
  }
}

export function useLiveConversation() {
  const [saved, setSaved] = useState(restore);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [results, setResults] = useState<Record<string, Turn>>({});
  const [handoff, setHandoff] = useState<HandoffState>();
  const [loading, setLoading] = useState(Boolean(saved.session));
  const [syncError, setSyncError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const latest = useRef(saved);
  const inFlight = useRef<AbortController | null>(null);
  const resultCache = useRef<Record<string, Turn>>({});
  const refreshNow = useRef<() => void>(() => {});
  const { session, pending } = saved;

  function commit(next: SavedChat) {
    sessionStorage.setItem(storageKey, JSON.stringify(next));
    latest.current = next;
    setSaved(next);
  }

  function record(turn: Turn) {
    resultCache.current = { ...resultCache.current, [turn.turn_id]: turn };
    setResults(resultCache.current);
  }

  useEffect(() => {
    if (!session) return;
    const activeSession = session;
    const controller = new AbortController();
    let timer: number;
    let running = false;
    let refreshQueued = false;

    async function refresh() {
      if (running) {
        refreshQueued = true;
        return;
      }
      running = true;
      window.clearTimeout(timer);
      const options = chatRequest(activeSession, { signal: controller.signal });
      try {
        const history = await json<ChatMessage[]>(`${chatPath(activeSession)}/messages`, options);
        if (controller.signal.aborted) return;
        setMessages(history);
        const pendingTurnId = latest.current.pending?.turnId;
        const turnIds = new Set(history.filter(item => item.role === 'user').map(item => item.turn_id));
        if (pendingTurnId) turnIds.add(pendingTurnId);
        const stale = [...turnIds].filter(id => resultCache.current[id]?.status !== 'succeeded');
        const updates = await Promise.allSettled(stale.map(id => json<Turn>(turnPath(activeSession, id), options)));
        if (controller.signal.aborted) return;
        for (const update of updates) {
          if (update.status === 'fulfilled') record(update.value);
        }
        if (pendingTurnId && latest.current.pending?.turnId === pendingTurnId &&
            resultCache.current[pendingTurnId]?.status === 'succeeded') {
          commit({ session: activeSession });
          setSubmitError('');
        }
        if (Object.values(resultCache.current).some(turn => turn.outcome === 'handoff')) {
          const state = await json<HandoffState>(`${chatPath(activeSession)}/support`, options).catch(() => undefined);
          if (!controller.signal.aborted && state) setHandoff(state);
        }
        setSyncError(updates.some(update => update.status === 'rejected') ? 'Часть переписки ещё не загрузилась.' : '');
      } catch (error) {
        if (!controller.signal.aborted) setSyncError(error instanceof ApiError && error.status === 404
          ? 'Этот диалог больше недоступен. Начните новый диалог.'
          : 'Соединение прервалось. Обновляем переписку…');
      } finally {
        running = false;
        if (!controller.signal.aborted) {
          setLoading(false);
          timer = window.setTimeout(refresh, refreshQueued ? 0 : latest.current.pending?.turnId ? 850 : document.hidden ? 5000 : 1500);
          refreshQueued = false;
        }
      }
    }

    refreshNow.current = () => { void refresh(); };
    window.addEventListener('focus', refreshNow.current);
    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      window.removeEventListener('focus', refreshNow.current);
      refreshNow.current = () => {};
    };
  }, [session, attempt]);

  useEffect(() => {
    const interrupted = latest.current.pending;
    if (interrupted && !interrupted.turnId) void deliver(interrupted);
    return () => inFlight.current?.abort();
  }, []);

  async function deliver(message: Pending, retryFailed = false) {
    if (inFlight.current) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setBusy(true);
    setSubmitError('');
    try {
      let activeSession = latest.current.session;
      if (!activeSession) {
        activeSession = await json<ChatSession>('/chats', { method: 'POST', signal: controller.signal });
        commit({ session: activeSession, pending: message });
      }
      const options = chatRequest(activeSession, { method: 'POST', signal: controller.signal });
      if (retryFailed && message.turnId) {
        try {
          await json(`${turnPath(activeSession, message.turnId)}/retry`, options);
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 409)) throw error;
        }
        const current = await json<Turn>(turnPath(activeSession, message.turnId),
          chatRequest(activeSession, { signal: controller.signal }));
        record(current);
      } else if (!message.turnId) {
        const { turn_id } = await json<{ turn_id: string }>(`${chatPath(activeSession)}/${message.manager ? 'manager-messages' : 'messages'}`, {
          ...options, body: JSON.stringify({ client_message_id: message.id, text: message.text }),
        });
        commit({ session: activeSession, pending: { ...message, turnId: turn_id } });
      }
      refreshNow.current();
    } catch (error) {
      if (!controller.signal.aborted) setSubmitError(error instanceof ApiError && error.status === 404
        ? 'Не удалось восстановить диалог. Можно начать новый.'
        : 'Не удалось получить подтверждение. Повторите отправку, чтобы продолжить этот же запрос.');
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null;
        setBusy(false);
      }
    }
  }

  function send(text: string, manager = false) {
    if (inFlight.current || latest.current.pending) return false;
    const message = { id: crypto.randomUUID(), text, manager };
    try {
      commit({ ...latest.current, pending: message });
    } catch {
      setSubmitError('Включите хранение данных для этого сайта, чтобы чат мог восстановить отправку.');
      return false;
    }
    void deliver(message);
    return true;
  }

  function retry() {
    const message = latest.current.pending;
    if (message) void deliver(message, Boolean(message.turnId && resultCache.current[message.turnId]?.status === 'failed'));
  }

  function reset() {
    inFlight.current?.abort();
    inFlight.current = null;
    commit({});
    resultCache.current = {};
    setResults({});
    setMessages([]);
    setHandoff(undefined);
    setSubmitError('');
    setSyncError('');
    setBusy(false);
    setLoading(false);
    setAttempt(value => value + 1);
  }

  const pendingFailed = Boolean(pending?.turnId && results[pending.turnId]?.status === 'failed');
  return {
    session, pending, pendingFailed, messages, results, handoff, loading, busy, syncError, submitError,
    send, retry, reset, record, refresh: () => refreshNow.current(),
  };
}
