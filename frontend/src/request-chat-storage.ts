import type { Message } from './agent-types';
import type { OperatorStatus } from './operator-types';

export type ChatDraft = { text: string; files: File[] };
export type SupportMessage = { id: string; draft: ChatDraft; sentAt?: number };
type CustomerMessage = Message & { id: string; role: 'user'; sentAt: number };

export type StoredChat = {
  taken: boolean;
  messages: SupportMessage[];
  customerMessages?: CustomerMessage[];
  workflow?: { status: OperatorStatus; updatedAt: number; replyTo?: string };
};

const emptyChat: StoredChat = { taken: false, messages: [] };
const changeKey = 'softline-store-support-changed';

export function demoChatKey(requestId: string, conversationId: string | null) {
  return JSON.stringify([requestId, conversationId, null]);
}

function notifyChatChange(key: string) {
  window.dispatchEvent(new CustomEvent(changeKey, { detail: key }));
  try {
    localStorage.setItem(changeKey, JSON.stringify([key, performance.timeOrigin, performance.now()]));
  } catch { /* The same-tab notification is still available. */ }
}

export function subscribeToChatChanges(listener: (key: string) => void) {
  function onLocalChange(event: Event) {
    listener((event as CustomEvent<string>).detail);
  }

  function onStorage(event: StorageEvent) {
    if (event.key !== changeKey || !event.newValue) return;
    let key: unknown;
    try { [key] = JSON.parse(event.newValue); } catch { return; }
    if (typeof key === 'string') listener(key);
  }

  window.addEventListener(changeKey, onLocalChange);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(changeKey, onLocalChange);
    window.removeEventListener('storage', onStorage);
  };
}

function openDatabase() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open('softline-store-support', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('chats');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function readSupportChats(keys: string[]) {
  const db = await openDatabase();
  try {
    const chat = db.transaction('chats').objectStore('chats');
    return await Promise.all(keys.map(key => new Promise<StoredChat | undefined>((resolve, reject) => {
      const request = chat.get(key);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    })));
  } finally {
    db.close();
  }
}

export async function readSupportChat(key: string) {
  const [chat] = await readSupportChats([key]);
  return chat;
}

async function updateSupportChat(key: string, change: (chat: StoredChat) => StoredChat) {
  const db = await openDatabase();
  try {
    const updated = await new Promise<StoredChat>((resolve, reject) => {
      const transaction = db.transaction('chats', 'readwrite');
      const chat = transaction.objectStore('chats');
      const current = chat.get(key);
      let next = emptyChat;
      current.onsuccess = () => {
        try {
          next = change(current.result ?? emptyChat);
          chat.put(next, key);
        } catch (error) {
          transaction.abort();
          reject(error);
        }
      };
      transaction.oncomplete = () => resolve(next);
      transaction.onabort = () => reject(transaction.error);
    });
    notifyChatChange(key);
    return updated;
  } finally {
    db.close();
  }
}

function nextTimestamp(chat: StoredChat) {
  return Math.max(Date.now(), (chat.messages.at(-1)?.sentAt ?? 0) + 1,
    (chat.customerMessages?.at(-1)?.sentAt ?? 0) + 1, (chat.workflow?.updatedAt ?? 0) + 1);
}

export function saveSupportAction(key: string, message?: SupportMessage, replyingTo?: string) {
  return updateSupportChat(key, chat => {
    if (chat.workflow?.status === 'resolved') throw new Error('Request is closed');
    if (!message || chat.messages.some(item => item.id === message.id)) return { ...chat, taken: true };
    const sentAt = nextTimestamp(chat);
    const workflow = chat.workflow?.replyTo && chat.workflow.replyTo === replyingTo
      ? { status: 'review' as const, updatedAt: chat.workflow.updatedAt }
      : chat.workflow;
    return { ...chat, taken: true, workflow, messages: [...chat.messages, { ...message, sentAt }] };
  });
}

export function saveRequestStatus(key: string, status: OperatorStatus, lastSeenCustomerId?: string) {
  return updateSupportChat(key, chat => {
    const latest = chat.customerMessages?.at(-1);
    const updatedAt = nextTimestamp(chat);
    const workflow = status === 'waiting' && latest && latest.id !== lastSeenCustomerId
      ? { status: 'review' as const, updatedAt, replyTo: latest.id }
      : { status, updatedAt };
    return { ...chat, workflow };
  });
}

export function saveCustomerReply(key: string, id: string, content: string) {
  return updateSupportChat(key, chat => {
    if (chat.workflow?.status === 'resolved') throw new Error('Request is closed');
    if (chat.customerMessages?.some(message => message.id === id)) return chat;
    const sentAt = nextTimestamp(chat);
    const message: CustomerMessage = { id, content, role: 'user', sentAt };
    const workflow = chat.workflow?.status === 'waiting' || chat.workflow?.replyTo
      ? { status: 'review' as const, updatedAt: sentAt, replyTo: id }
      : chat.workflow;
    return { ...chat, workflow, customerMessages: [...(chat.customerMessages ?? []), message] };
  });
}
