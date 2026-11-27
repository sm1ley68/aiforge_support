import { useEffect, useState, useSyncExternalStore } from 'react';
import type { OperatorRequest } from './operator-types';
import { demoChatKey, readSupportChat, saveSupportAction, subscribeToChatChanges, type ChatDraft, type SupportMessage } from './request-chat-storage';

export const attachmentLimit = 5;
export const attachmentBytesLimit = 10 * 1024 * 1024;
const endpoint = import.meta.env.VITE_SUPPORT_MESSAGES_URL?.trim();
const demoSupport = !endpoint;
const emptyDraft: ChatDraft = { text: '', files: [] };

type ChatState = {
  ready: boolean;
  taken: boolean;
  taking: boolean;
  draft: ChatDraft;
  pending?: SupportMessage;
  messages: SupportMessage[];
  error: string;
  storageWarning: string;
};

function encodeFile(file: File) {
  return new Promise<{ name: string; contentType: string; size: number; contentBase64: string }>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const data = String(reader.result);
      resolve({
        name: file.name,
        contentType: file.type || 'application/octet-stream',
        size: file.size,
        contentBase64: data.slice(data.indexOf(',') + 1),
      });
    };
    reader.readAsDataURL(file);
  });
}

async function postSupport(request: OperatorRequest, action: 'takeover' | 'message', payload: Record<string, unknown> = {}) {
  if (!endpoint) throw new Error('Support endpoint is missing');
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, requestId: request.id, conversationId: request.response.conversationId, ...payload }),
  });
  if (!response.ok) throw new Error(`Support action failed (HTTP ${response.status})`);
}

function createRequestChat(request: OperatorRequest, key: string) {
  const ownedBySupport = request.handledBy === 'support'
    || (request.handledBy === undefined && request.response.messages.some(message => message.role === 'support'));
  let state: ChatState = { ready: !demoSupport, taken: ownedBySupport, taking: false, draft: emptyDraft, messages: [], error: '', storageWarning: '' };
  let readVersion = 0;
  let retryId: string | undefined;
  const listeners = new Set<() => void>();

  function update(next: Partial<ChatState>) {
    state = { ...state, ...next };
    listeners.forEach(listener => listener());
  }

  async function refresh() {
    const version = ++readVersion;
    try {
      const saved = await readSupportChat(key);
      if (version === readVersion) {
        update({ ready: true, taken: Boolean(saved?.taken || ownedBySupport), messages: saved?.messages ?? [], storageWarning: '' });
      }
    } catch {
      if (version === readVersion) update({ ready: true, storageWarning: 'Браузер не открыл сохранённую историю.' });
    }
  }

  async function takeOver() {
    if (!state.ready || state.taken || state.taking) return;
    if (!demoSupport && !endpoint) {
      update({ error: 'Канал отправки клиенту пока не подключён.' });
      return;
    }
    update({ taking: true, error: '' });
    try {
      if (demoSupport) await saveSupportAction(key);
      else await postSupport(request, 'takeover');
      update({ taken: true });
    } catch {
      update({ error: 'Не удалось взять диалог в работу. Попробуйте ещё раз.' });
    } finally {
      update({ taking: false });
    }
  }

  async function send(replyingTo?: string) {
    const draft = { ...state.draft, text: state.draft.text.trim() };
    if (!state.ready || !state.taken || state.pending || (!draft.text && !draft.files.length)) return;
    if (draft.files.length > attachmentLimit || draft.files.reduce((total, file) => total + file.size, 0) > attachmentBytesLimit) return;
    if (!demoSupport && !endpoint) {
      update({ error: 'Канал отправки клиенту пока не подключён.' });
      return;
    }

    const id = retryId ?? (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    const message = { id, draft, sentAt: Date.now() };
    update({ pending: message, draft: emptyDraft, error: '' });
    try {
      let messages: SupportMessage[];
      if (demoSupport) {
        const saved = await saveSupportAction(key, message, replyingTo);
        const committed = new Set(saved.messages.map(item => item.id));
        messages = [...saved.messages, ...state.messages.filter(item => !committed.has(item.id))];
      } else {
        const attachments = draft.files.length ? await Promise.all(draft.files.map(encodeFile)) : undefined;
        await postSupport(request, 'message', {
          clientMessageId: id,
          content: draft.text,
          ...(attachments && { attachments }),
        });
        messages = [...state.messages, message];
      }
      retryId = undefined;
      update({ messages, pending: undefined });
    } catch {
      retryId = id;
      update({ pending: undefined, draft, error: 'Не удалось отправить сообщение. Текст и файлы остались в черновике.' });
    }
  }

  return {
    refresh,
    takeOver,
    send,
    getSnapshot: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    setDraft(draft: ChatDraft) {
      if (state.pending) return;
      retryId = undefined;
      update({ draft, error: '' });
    },
  };
}

export type RequestChatState = ReturnType<typeof useRequestChat>;
const chats = new Map<string, ReturnType<typeof createRequestChat>>();

export function useRequestChat(request: OperatorRequest) {
  const demoKey = demoChatKey(request.id, request.response.conversationId);
  const [chat] = useState(() => {
    const key = demoSupport ? demoKey : JSON.stringify([request.id, request.response.conversationId, request.updatedAt]);
    const session = chats.get(key) ?? createRequestChat(request, key);
    chats.set(key, session);
    return session;
  });
  const state = useSyncExternalStore(chat.subscribe, chat.getSnapshot);

  useEffect(() => {
    if (!demoSupport) return;
    void chat.refresh();
    return subscribeToChatChanges(key => { if (key === demoKey) void chat.refresh(); });
  }, [chat, demoKey]);

  return { ...state, demo: demoSupport, send: chat.send, takeOver: chat.takeOver, setDraft: chat.setDraft };
}
