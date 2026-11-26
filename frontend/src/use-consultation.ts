import { useEffect, useRef, useState } from 'react';
import { createAgentClient } from '../agent-client.mjs';
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
  const [response, setResponse] = useState<AgentResponse>(isDemo && seedDemo && !catalogProductId ? demoConversation : empty);
  const [messages, setMessages] = useState<Message[]>(response.messages);
  const [scenario, setScenario] = useState<Scenario | null>(catalogProductId || response.conversationId ? 'known' : null);
  const [productId, setProductId] = useState(catalogProductId || undefined);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [session, setSession] = useState(0);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function send(text = draft) {
    const message = text.trim();
    if (!message || activeRequest.current) return;

    const controller = new AbortController();
    const userMessage: Message = { role: 'user', content: message };
    activeRequest.current = controller;
    setMessages([...messages, userMessage]);
    setDraft('');
    setError('');
    setPending(true);

    try {
      const next = await client.send({
        conversationId: response.conversationId,
        message,
        scenario,
        history: messages,
        catalogProductId: productId,
      }, { signal: controller.signal });

      if (controller.signal.aborted) return;

      const reply = next.reply || next.messages.findLast(item => item.role === 'assistant')?.content;
      if (!reply) throw new Error('Empty agent reply');

      setMessages([...messages, userMessage, { role: 'assistant', content: reply }]);
      setResponse(next);
    } catch {
      if (controller.signal.aborted) return;

      setMessages(messages);
      setDraft(current => current || message);
      setError('Ответ не загрузился. Отправьте сообщение ещё раз.');
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setPending(false);
      }
    }
  }

  function reset(nextScenario: Scenario | null = null) {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setResponse(empty);
    setMessages([]);
    setScenario(nextScenario);
    setProductId(undefined);
    setDraft('');
    setPending(false);
    setError('');
    setSession(current => current + 1);
  }

  return { response, messages, scenario, draft, setDraft, pending, error, session, send, reset };
}
