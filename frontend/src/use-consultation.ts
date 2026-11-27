import { useEffect, useRef, useState } from 'react';
import { createAgentClient, newMessageId, type ConsultationAttempt } from '../agent-client.mjs';
import { demoConversation, mockAgent } from '../mock-agent.mjs';
import type { AgentResponse, Message, Scenario } from './agent-types';

const endpoint = import.meta.env.VITE_AGENT_API_URL?.trim() ?? '';
const catalogProductId = new URLSearchParams(window.location.search).get('product')?.trim();

export const isDemo = !endpoint;

const client = createAgentClient({ endpoint, mock: mockAgent });
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

export function useConsultation({ seedDemo = true }: { seedDemo?: boolean } = {}) {
  const [conversation, setConversation] = useState(() => {
    const response = isDemo && seedDemo && !catalogProductId ? demoConversation : empty;
    return { response, messages: response.messages };
  });
  const { response, messages } = conversation;
  const [scenario, setScenario] = useState<Scenario | null>(catalogProductId || response.conversationId ? 'known' : null);
  const [productId, setProductId] = useState(catalogProductId || undefined);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [session, setSession] = useState(0);
  const attemptRef = useRef<{ message: string; state: ConsultationAttempt } | null>(null);
  const chatRef = useRef<ConsultationAttempt['chat']>(undefined);
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

    const previous = attemptRef.current;
    const attempt = previous?.message === message
      ? previous.state
      : { messageId: newMessageId(), chat: chatRef.current };
    attemptRef.current = { message, state: attempt };

    try {
      const next = await client.send({
        conversationId: response.conversationId,
        message,
        scenario,
        history: messages,
        catalogProductId: productId,
      }, { signal: controller.signal, attempt });

      if (controller.signal.aborted) return;

      const reply = next.reply || next.messages.findLast(item => item.role === 'assistant')?.content;
      if (!reply) throw new Error('Empty agent reply');

      attemptRef.current = null;
      setConversation({
        response: next,
        messages: attempt.chat && next.messages.length ? next.messages : [...pendingMessages, { role: 'assistant', content: reply }],
      });
    } catch {
      if (controller.signal.aborted) return;

      setConversation(conversation);
      setDraft(current => current || message);
      setError('Ответ не загрузился. Отправьте сообщение ещё раз.');
    } finally {
      if (activeRequest.current === controller) {
        chatRef.current = attempt.chat;
        activeRequest.current = null;
        setPending(false);
      }
    }
  }

  function reset(nextScenario: Scenario | null = null) {
    activeRequest.current?.abort();
    activeRequest.current = null;
    attemptRef.current = null;
    chatRef.current = undefined;
    setConversation({ response: empty, messages: empty.messages });
    setScenario(nextScenario);
    setProductId(undefined);
    setDraft('');
    setPending(false);
    setError('');
    setSession(current => current + 1);
  }

  return { response, messages, scenario, draft, setDraft, pending, error, session, send, reset };
}
