import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent, ReactNode } from 'react';
import { AppIcon } from './AppIcon';
import type { IconName } from './AppIcon';
import { ChatDownload } from './RequestMessages';
import { StoreRibbon } from './StoreRibbon';
import { demoChatKey, readSupportChat, saveCustomerReply, subscribeToChatChanges, type StoredChat } from './request-chat-storage';
import {
  emptyStoreConversation, loadStoreConversation, replyToStoreMessage,
  saveDemoHandoff, saveStoreConversation, starters, voronezh,
} from './store-advisor-demo';
import type { DemoTurn, StoreConversation } from './store-advisor-demo';
import './store-advisor.css';

const resultStatus = {
  fit: 'Подходит',
  alternative: 'Альтернатива',
  option: 'Вариант',
  check: 'Требует проверки',
  mismatch: 'Ниже требования',
};

function StoreLink({ children, href, className }: { children: ReactNode; href: string; className?: string }) {
  return <a className={className} href={href} target="_blank" rel="noreferrer">{children} <AppIcon name="external" size={14} /></a>;
}

function Comparison({ turn }: { turn: DemoTurn }) {
  const results = turn.reply.results ?? [];
  if (results.length < 2) return null;
  const labels = [...new Set(results.flatMap(({ offer }) => offer.facts.map(([label]) => label)))];
  return (
    <details className="store-comparison">
      <summary>Сравнить варианты <AppIcon name="chevron" size={14} /></summary>
      <table>
        <caption className="store-visually-hidden">Сравнение характеристик вариантов</caption>
        <thead><tr><th scope="col">Критерий</th>
          {results.map(({ offer }) => <th key={offer.id} scope="col">{offer.title.replace('Astra Linux SE ', '')}</th>)}
        </tr></thead>
        <tbody>
          {labels.map(label => (
            <tr key={label}><th scope="row">{label}</th>
              {results.map(({ offer }) => <td key={offer.id}>{offer.facts.find(([key]) => key === label)?.[1] ?? 'Уточнить'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function TurnReply({ turn }: { turn: DemoTurn }) {
  const { text, changed, results, source } = turn.reply;
  return (
    <div className="store-reply">
      <div className="store-reply-by"><span><AppIcon name="mark" size={14} /></span> Помощник Store</div>
      {changed && <p className="store-change"><AppIcon name="comparisonMatch" size={17} />{changed}</p>}
      <p className="store-reply-text">{text}</p>
      {source && <StoreLink className="store-inline-source" href={source.url}>{source.title}</StoreLink>}
      {results && (
        <div className="store-results">
          {results.map(({ offer, status }) => (
            <article className="store-result" data-status={status} key={offer.id}>
              <span className="store-result-state">
                {status === 'fit' && <AppIcon name="comparisonMatch" size={13} />}
                {resultStatus[status]}
              </span>
              <h3>{offer.title}</h3>
              <p>{offer.reason}</p>
              <details>
                <summary>Характеристики <AppIcon name="chevron" size={13} /></summary>
                <dl>
                  {offer.facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
                  {offer.sku && <div><dt>Артикул</dt><dd>{offer.sku}</dd></div>}
                </dl>
              </details>
              <StoreLink className="store-result-link" href={offer.url}>Открыть в Store</StoreLink>
            </article>
          ))}
          <Comparison turn={turn} />
        </div>
      )}
    </div>
  );
}

const starterIcons: IconName[] = ['products', 'search', 'sources'];

type PanelProps = {
  conversation: StoreConversation;
  waiting: string | null;
  draft: string;
  setDraft: (text: string) => void;
  error: string;
  linkedChat?: StoredChat;
  sending: boolean;
  hasProductContext: boolean;
  reset: () => void;
  send: (text: string) => void;
};

function AdvisorPanel({ conversation, waiting, draft, setDraft, error, linkedChat, sending, hasProductContext, reset, send }: PanelProps) {
  const transcript = useRef<HTMLDivElement>(null);
  const lastTurn = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const hadFocus = useRef(false);
  const last = conversation.turns.at(-1);
  const closed = linkedChat?.workflow?.status === 'resolved';
  const followUps = [
    ...(linkedChat?.messages ?? []).map(({ id, draft, sentAt }) => ({ id, text: draft.text, files: draft.files, sentAt: sentAt ?? 0 })),
    ...(linkedChat?.customerMessages ?? []).map(({ id, content, sentAt }) => ({ id, text: content, files: null, sentAt })),
  ].sort((first, second) => first.sentAt - second.sentAt);

  useLayoutEffect(() => {
    const viewport = transcript.current;
    const start = lastTurn.current;
    if (!viewport || !start) return;
    viewport.scrollTop += start.getBoundingClientRect().top - viewport.getBoundingClientRect().top - 12;
  }, [last?.id, waiting]);

  useLayoutEffect(() => {
    const viewport = transcript.current;
    if (viewport && followUps.length) viewport.scrollTop = viewport.scrollHeight;
  }, [followUps.length]);

  function prefill(text: string) {
    setDraft(text);
    input.current?.focus();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send(draft);
    input.current?.focus();
  }

  function onEditorKeys(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !window.matchMedia('(pointer: coarse)').matches) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  useEffect(() => {
    if (!waiting && hadFocus.current && !conversation.handoffId) input.current?.focus({ preventScroll: true });
    if (!waiting) hadFocus.current = false;
  }, [waiting, conversation.handoffId]);

  const talkToManager = () => send('Позовите менеджера.');
  const hasTurns = conversation.turns.length > 0;

  return (
    <section className="store-panel" aria-labelledby="store-panel-title">
      <header className="store-panel-head">
        <span className="store-panel-mark"><AppIcon name="mark" size={24} /></span>
        <div className="store-panel-heading">
          <h1 id="store-panel-title">Помощник Softline</h1>
          <p>Подбор ПО и лицензий</p>
        </div>
      </header>
      {hasProductContext && (
        <div className="store-context">
          <AppIcon name="products" size={17} />
          <span>Выбранный товар</span>
          <StoreLink href={voronezh.url}>{voronezh.title}</StoreLink>
        </div>
      )}
      {hasTurns ? (
        <div className="store-transcript" ref={transcript} role="log" aria-label="Переписка" tabIndex={0}>
          {conversation.turns.map(turn => (
            <div key={turn.id} className="store-turn" ref={turn.id === last?.id ? lastTurn : undefined}>
              <p className="store-user-message"><span className="store-visually-hidden">Вы: </span>{turn.message}</p>
              {waiting === turn.id
                ? <p className="store-pending" role="status"><span aria-hidden="true"><i /><i /><i /></span> Готовлю ответ…</p>
                : <TurnReply turn={turn} />}
            </div>
          ))}
          {!waiting && !conversation.handoffId && last?.reply.choices && (
            <div className="store-choices" aria-label="Быстрые ответы">
              {last.reply.choices.map(choice => (
                <button key={choice.text} type="button" onClick={() => { hadFocus.current = !window.matchMedia('(pointer: coarse)').matches; send(choice.text); }}>{choice.label}</button>
              ))}
            </div>
          )}
          {!waiting && !conversation.handoffId && last?.reply.offerHandoff && (
            <button type="button" className="store-handoff-inline" onClick={talkToManager}><AppIcon name="support" size={16} /> Передать требования менеджеру</button>
          )}
          {!waiting && conversation.handoffId && (
            <div className="store-handoff-done">
              <AppIcon name="resolved" size={19} />
              <div><strong>Обращение {conversation.handoffId}</strong><a href={`?request=${encodeURIComponent(conversation.handoffId)}`} target="_blank" rel="noreferrer">Открыть кейс менеджера <AppIcon name="external" size={14} /></a></div>
            </div>
          )}
          {followUps.map(message => (
            <div className="store-turn store-follow-up" key={message.id}>
              {message.files ? (
                <div className="store-reply">
                  <div className="store-reply-by"><span><AppIcon name="support" size={14} /></span> Менеджер Softline</div>
                  {message.text && <p className="store-reply-text">{message.text}</p>}
                  {message.files.length > 0 && (
                    <ul className="store-support-files" aria-label="Файлы от менеджера">
                      {message.files.map((file, index) => <li key={index}><ChatDownload file={file} /></li>)}
                    </ul>
                  )}
                </div>
              ) : (
                <p className="store-user-message"><span className="store-visually-hidden">Вы: </span>{message.text}</p>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="store-chat-start">
          <h2>Здравствуйте! Чем помочь?</h2>
          <p>Опишите задачу своими словами или начните с одного из вопросов.</p>
          <div className="store-starters" aria-label="Примеры вопросов">
            {starters.map((starter, index) => (
              <button type="button" key={starter.label} onClick={() => prefill(starter.text)}>
                <AppIcon name={starterIcons[index]} size={18} /> <span>{starter.label}</span> <AppIcon name="chevron" size={14} />
              </button>
            ))}
          </div>
        </div>
      )}
      <footer className="store-panel-footer">
        {error && <p className="store-form-error" role="alert">{error}</p>}
        {closed && <p className="store-closed-note">Обращение закрыто.</p>}
        {!closed && (
          <form className="store-composer" onSubmit={submit}>
            <label className="store-visually-hidden" htmlFor="store-question">Сообщение помощнику</label>
            <textarea id="store-question" ref={input} rows={2} maxLength={1200} value={draft} readOnly={sending}
              placeholder={conversation.handoffId ? 'Напишите менеджеру…' : 'Напишите вопрос…'}
              onChange={event => setDraft(event.currentTarget.value)} onKeyDown={onEditorKeys} />
            <button type="submit" aria-label="Отправить сообщение" title="Отправить сообщение" disabled={!draft.trim() || !!waiting || sending}>
              <AppIcon name="send" size={20} />
            </button>
          </form>
        )}
        <div className="store-footer-actions">
          {!conversation.handoffId && <button type="button" disabled={!!waiting} onClick={talkToManager}><AppIcon name="support" size={16} /> Позвать менеджера</button>}
          {hasTurns && <button type="button" disabled={!!waiting || sending} onClick={reset}>Новый диалог</button>}
        </div>
      </footer>
    </section>
  );
}

export function StoreAdvisor() {
  const hasProductContext = new URLSearchParams(window.location.search).get('product') === voronezh.id;
  const [conversation, setConversation] = useState(loadStoreConversation);
  const [draft, setDraft] = useState('');
  const [waiting, setWaiting] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [linked, setLinked] = useState<{ key: string; chat?: StoredChat }>();
  const [sending, setSending] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendingToSupport = useRef(false);
  const linkedKey = conversation.handoffId && demoChatKey(conversation.handoffId, conversation.handoffId);
  const linkedChat = linked?.key === linkedKey ? linked?.chat : undefined;

  useEffect(() => {
    const title = document.title;
    document.title = 'Чат с помощником | Softline';
    return () => { document.title = title; if (timer.current) clearTimeout(timer.current); };
  }, []);

  useEffect(() => {
    if (!linkedKey) return;
    let active = true;
    let generation = 0;
    async function refresh(key: string) {
      const current = ++generation;
      try {
        const chat = await readSupportChat(key);
        if (active && generation === current) setLinked({ key, chat });
      } catch { /* The initial conversation remains visible if browser storage is unavailable. */ }
    }
    void refresh(linkedKey);
    const unsubscribe = subscribeToChatChanges(key => { if (key === linkedKey) void refresh(key); });
    return () => { active = false; unsubscribe(); };
  }, [linkedKey]);

  function updateConversation(next: StoreConversation) {
    saveStoreConversation(next);
    setConversation(next);
  }

  function send(raw: string) {
    const message = raw.trim();
    if (!message || timer.current || sendingToSupport.current) return;
    const id = crypto.randomUUID?.() ?? [...crypto.getRandomValues(new Uint8Array(16))]
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
    if (linkedKey) {
      if (linkedChat?.workflow?.status === 'resolved') return;
      sendingToSupport.current = true;
      setSending(true);
      setError('');
      void saveCustomerReply(linkedKey, id, message).then(
        () => setDraft(''),
        () => setError('Не удалось передать сообщение менеджеру. Попробуйте ещё раз.'),
      ).finally(() => {
        sendingToSupport.current = false;
        setSending(false);
      });
      return;
    }
    const { reply, requirements, handoff } = replyToStoreMessage(message, conversation.requirements);
    const next: StoreConversation = { requirements, turns: [...conversation.turns, { id, message, reply, topic: requirements.topic }] };
    if (handoff) {
      const requestId = `DEMO-${id.slice(0, 8).toUpperCase()}`;
      try {
        saveDemoHandoff(requestId, next);
        next.handoffId = requestId;
      } catch {
        setError('Не удалось сохранить обращение в браузере. Попробуйте ещё раз.');
        return;
      }
    }
    setDraft('');
    setError('');
    setWaiting(id);
    updateConversation(next);
    timer.current = setTimeout(() => {
      timer.current = null;
      setWaiting(null);
    }, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 420);
  }

  function reset() {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    updateConversation(emptyStoreConversation());
    setDraft('');
    setWaiting(null);
    setError('');
  }

  return (
    <main className="store-demo">
      <StoreRibbon />
      <AdvisorPanel conversation={conversation} draft={draft} setDraft={setDraft} error={error} waiting={waiting}
        linkedChat={linkedChat} sending={sending} hasProductContext={hasProductContext} reset={reset} send={send} />
    </main>
  );
}
