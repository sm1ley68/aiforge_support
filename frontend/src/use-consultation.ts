import { useEffect, useRef, useState } from 'react';
import { createAgentClient } from '../agent-client.mjs';
import type { AgentResponse, Message, Scenario } from './agent-types';

const endpoint = import.meta.env.VITE_AGENT_API_URL?.trim() || '/api/consultation';
const catalogProductId = new URLSearchParams(window.location.search).get('product')?.trim();

const client = createAgentClient({ endpoint });
const empty: AgentResponse = {
  conversationId: null,
  messages: [],
  reply: '',
  requirements: [],
  products: [],
  sources: [],
  trace: [],
  suggestedReplies: [],
};

export function useConsultation() {
  const [conversation, setConversation] = useState({ response: empty, messages: empty.messages });
  const { response, messages } = conversation;
  const scenario: Scenario | null = catalogProductId ? 'known' : null;
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => {
    activeRequest.current?.abort();
    activeRequest.current = null;
  }, []);

  async function send(text = draft) {
    const message = text.trim();
    if (!message || activeRequest.current) return;

    const controller = new AbortController();
    const userMessage: Message = { role: 'user', content: message };
    const pendingMessages = [...messages, userMessage];
    activeRequest.current = controller;
    setConversation({ response, messages: pendingMessages });
    setDraft('');
    setError('');
    setPending(true);

    try {
      const next = await client.send({
        conversationId: response.conversationId,
        message,
        scenario,
        history: messages,
        catalogProductId: catalogProductId || undefined,
      }, { signal: controller.signal });

      if (controller.signal.aborted) return;

      const reply = next.reply || next.messages.findLast(item => item.role === 'assistant')?.content;
      if (!reply) throw new Error('Empty agent reply');

      setConversation({ response: next, messages: [...pendingMessages, { role: 'assistant', content: reply }] });
    } catch {
      if (controller.signal.aborted) return;

      setConversation(conversation);
      setDraft(current => current || message);
      setError('Ответ не загрузился. Отправьте сообщение ещё раз.');
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setPending(false);
      }
    }
  }

  return { response, messages, draft, setDraft, pending, error, send };
}
