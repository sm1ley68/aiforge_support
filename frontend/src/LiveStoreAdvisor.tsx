import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { AppIcon } from './AppIcon';
import { DemoNotice } from './DemoNotice';
import type { IconName } from './AppIcon';
import { StoreRibbon } from './StoreRibbon';
import { ApiError, api, chatPath, chatRequest, formatCatalogDate, formatPrice, json, safeLink, turnPath } from './softline-api';
import type { Availability, ChatSession, HandoffState, Quote, QuoteCustomer, Turn } from './softline-api';
import type { Source } from './agent-types';
import { useLiveConversation } from './use-live-conversation';
import './store-advisor.css';
import './store-advisor-live.css';

function SourceLink({ source }: { source: Source }) {
  const href = safeLink(source.url);
  if (!href) return null;
  return <a className="store-inline-source" href={href} target="_blank" rel="noreferrer">{source.title} <AppIcon name="external" size={14} /></a>;
}

function QuoteCard({ quote, session, turnId, onSaved }: {
  quote: Quote; session: ChatSession; turnId: string; onSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const path = `${turnPath(session, turnId)}/quote`;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const customer: QuoteCustomer = {
      company: String(data.get('company')).trim(),
      inn: String(data.get('inn')).trim(),
      kpp: String(data.get('kpp')).trim().toUpperCase(),
    };
    setBusy(true);
    setError('');
    try {
      await api(`${path}/customer`, chatRequest(session, { method: 'PUT', body: JSON.stringify(customer) }));
      await onSaved();
      setEditing(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await onSaved().catch(() => {});
        setError('У КП уже есть сохранённые реквизиты.');
      } else {
        setError('Не удалось сохранить реквизиты. Проверьте поля и повторите.');
      }
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setBusy(true);
    setError('');
    try {
      const response = await api(path, chatRequest(session));
      const filename = response.headers.get('Content-Disposition')?.match(/filename="([\w.-]+)"/)?.[1] ?? 'Коммерческое предложение.html';
      const href = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = href;
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(href), 1000);
    } catch {
      setError('Не удалось скачать КП. Попробуйте ещё раз.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="store-quote">
      <div className="store-quote-head">
        <div><p>Коммерческое предложение</p><h3>{quote.title}</h3></div>
        <strong>{formatPrice(quote.total, quote.currency)}</strong>
      </div>
      <p className="store-quote-calculation">{quote.quantity} {quote.unit_label} × {formatPrice(quote.unit_price, quote.currency)}{quote.vat_label && ` · ${quote.vat_label}`}</p>
      <p className="store-quote-meta">{quote.price_origin_label} от <time dateTime={quote.catalog_snapshot_at}>{formatCatalogDate(quote.catalog_snapshot_at)}</time></p>
      <SourceLink source={quote.source} />
      {quote.delivery_status === 'requires_confirmation' && <p className="store-delivery-note"><AppIcon name="review" size={15} /> Поставка требует подтверждения</p>}
      {quote.customer ? (
        <div className="store-quote-actions">
          <span>Реквизиты сохранены</span>
          <button className="store-primary" type="button" disabled={busy} onClick={() => void download()}><AppIcon name="download" size={16} /> Скачать КП</button>
        </div>
      ) : editing ? (
        <form className="store-live-form store-quote-form" onSubmit={save}>
          <label className="store-company-field">Название организации<input name="company" autoComplete="organization" required maxLength={200} /></label>
          <label>ИНН<input name="inn" inputMode="numeric" required pattern="[0-9]{10}([0-9]{2})?" maxLength={12} title="10 или 12 цифр" /></label>
          <label>КПП<input name="kpp" required pattern="[0-9]{4}[0-9A-Za-z]{2}[0-9]{3}" maxLength={9} autoCapitalize="characters" title="9 символов" /></label>
          <div className="store-quote-actions">
            <button type="button" disabled={busy} onClick={() => { setEditing(false); setError(''); }}>Отмена</button>
            <button className="store-primary" type="submit" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить реквизиты'}</button>
          </div>
        </form>
      ) : <div className="store-quote-actions"><button className="store-primary" type="button" onClick={() => setEditing(true)}>Добавить реквизиты</button></div>}
      {error && <p className="store-form-error" role="alert">{error}</p>}
    </article>
  );
}

const dayNames = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];

function SupportCard({ session, support, state, refresh }: {
  session: ChatSession; support?: Availability | null; state?: HandoffState; refresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const availability = state?.support ?? support;
  const schedule = availability?.schedule;
  const email = availability?.email;

  async function saveContact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get('email')).trim();
    setBusy(true);
    setError('');
    try {
      await api(`${chatPath(session)}/support/contact`, chatRequest(session, {
        method: 'PUT', body: JSON.stringify({ email: value }),
      }));
      refresh();
    } catch {
      setError('Не удалось сохранить email. Попробуйте ещё раз.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="store-support-card" aria-label="Статус обращения">
      <strong><AppIcon name="support" size={17} /> Передано менеджеру</strong>
      {!state?.hasContact && state?.status !== 'resolved' && (
        <form className="store-live-form store-contact-form" onSubmit={saveContact}>
          <label>Оставьте email для связи<input name="email" type="email" autoComplete="email" required maxLength={254} placeholder="name@company.ru" /></label>
          <button className="store-primary" type="submit" disabled={busy}>{busy ? 'Сохраняем…' : 'Передать email'}</button>
        </form>
      )}
      {state?.hasContact && <div className="store-support-info" role="status">
        <p>Контакт сохранён. {availability?.message ?? 'Менеджер отвечает в рабочее время.'}</p>
        {schedule && <p>{schedule.weekdays.map(day => dayNames[day - 1]).join(', ')} · {schedule.start}–{schedule.end}{schedule.timezone === 'Europe/Moscow' ? ' МСК' : ` (${schedule.timezone})`}</p>}
        {email && /^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$/.test(email) && <a href={`mailto:${email}`}>{email}</a>}
      </div>}
      {state?.status === 'waiting' && <p className="store-support-info">Менеджер ждёт вашего ответа.</p>}
      {error && <p className="store-form-error" role="alert">{error}</p>}
    </section>
  );
}

function LiveReply({ turn, session, onQuoteSaved }: { turn: Turn; session: ChatSession; onQuoteSaved: () => Promise<void> }) {
  const products = turn.products.filter(product => product.offer_id !== turn.quote?.offer_id);
  const sources = turn.sources.filter(source => source.url !== turn.quote?.source.url);
  return (
    <div className="store-reply">
      <div className="store-reply-by"><span><AppIcon name="mark" size={14} /></span> Помощник Softline</div>
      {turn.from_manager_knowledge && <p className="store-knowledge-label"><AppIcon name="sources" size={14} /> Найдено в базе знаний</p>}
      {!turn.quote && turn.text && <p className="store-reply-text">{turn.text}</p>}
      {turn.quote && <QuoteCard quote={turn.quote} session={session} turnId={turn.turn_id} onSaved={onQuoteSaved} />}
      {products.length > 0 && <div className="store-results">
        {products.map(card => <article className="store-result" key={card.offer_id}>
          <h3>{card.title}</h3>
          <p>{card.match_summary}</p>
          {card.price_amount != null && card.currency && <p className="store-card-price">
            <strong>{formatPrice(card.price_amount, card.currency)}</strong> · Снимок каталога от <time dateTime={card.snapshot_at}>{formatCatalogDate(card.snapshot_at)}</time>
          </p>}
          {card.availability === false && <p className="store-delivery-note">Поставка требует подтверждения</p>}
          <SourceLink source={{ title: 'Карточка товара', url: card.url }} />
        </article>)}
      </div>}
      {sources.length > 0 && <div className="store-live-sources" aria-label="Источники">
        <strong>{sources.length === 1 ? 'Источник' : 'Источники'}</strong>
        {sources.map((source, index) => <SourceLink key={`${source.url}-${index}`} source={source} />)}
      </div>}
    </div>
  );
}

const prompts: { title: string; text: string; icon: IconName }[] = [
  { title: 'Рассчитать стоимость', text: 'КП на 2 лицензии, ID предложения ', icon: 'products' },
  { title: 'Подобрать решение', text: 'Подберите ПО для ', icon: 'search' },
  { title: 'Найти ключ активации', text: 'Где найти ключ активации после покупки?', icon: 'sources' },
];

export function LiveStoreAdvisor() {
  const chat = useLiveConversation();
  const [draft, setDraft] = useState('');
  const transcript = useRef<HTMLDivElement>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const lastUser = useRef<HTMLDivElement>(null);
  const firstHandoff = Object.values(chat.results).find(turn => turn.outcome === 'handoff');
  const latestHandoff = Object.values(chat.results).findLast(turn => turn.outcome === 'handoff');
  const hasConversation = chat.messages.length > 0 || Boolean(chat.pending) || chat.loading || chat.sessionUnavailable;
  const unsyncedMessage = chat.pending && !chat.messages.some(message => message.role === 'user' &&
      (message.turn_id === chat.pending?.turnId || message.client_message_id === chat.pending?.id))
    ? chat.pending : undefined;
  const lastMessage = chat.messages.at(-1);
  const lastUserId = chat.messages.findLast(message => message.role === 'user')?.turn_id;
  const closed = chat.handoff?.status === 'resolved';

  useEffect(() => {
    document.title = 'Чат с помощником | Softline';
  }, []);

  useLayoutEffect(() => {
    if (transcript.current && (unsyncedMessage || lastMessage?.author === 'manager')) {
      transcript.current.scrollTop = transcript.current.scrollHeight;
    }
  }, [unsyncedMessage?.id, lastMessage?.turn_id, lastMessage?.author, lastMessage?.text]);

  useLayoutEffect(() => {
    const viewport = transcript.current;
    const message = lastUser.current;
    if (viewport && message) viewport.scrollTop += message.getBoundingClientRect().top - viewport.getBoundingClientRect().top - 14;
  }, [lastUserId]);

  function send(raw: string) {
    if (raw.trim() && chat.send(raw.trim(), Boolean(firstHandoff))) setDraft('');
  }

  function editorKeys(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !window.matchMedia('(pointer: coarse)').matches) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <main className="store-demo">
      <StoreRibbon />
      <section className="store-panel" aria-labelledby="store-panel-title">
        <header className="store-panel-head">
          <span className="store-panel-mark"><AppIcon name="mark" size={24} /></span>
          <div className="store-panel-heading"><h1 id="store-panel-title">Помощник Softline</h1><p>Подбор ПО и лицензий</p></div>
          <a className="store-manager-link" href={window.location.pathname} target="_blank" rel="noopener" aria-label="Кабинет менеджера">Кабинет менеджера <AppIcon name="external" size={13} /></a>
        </header>
        <DemoNotice />
        {hasConversation ? (
          <div className="store-transcript" ref={transcript} role="log" aria-label="Переписка" tabIndex={0}>
            {chat.loading && <p className="store-pending" role="status">Загружаем переписку…</p>}
            {chat.messages.map((message, index) => {
              const turn = chat.results[message.turn_id];
              return <div className="store-turn" key={`${message.turn_id}-${message.role}-${index}`}
                ref={message.role === 'user' && message.turn_id === lastUserId ? lastUser : undefined}>
                {message.role === 'user' ? <p className="store-user-message"><span className="store-visually-hidden">Вы: </span>{message.text}</p>
                  : message.author === 'manager' ? <div className="store-reply">
                      <div className="store-reply-by"><span><AppIcon name="support" size={14} /></span> Менеджер Softline</div>
                      <p className="store-reply-text">{message.text}</p>
                    </div>
                  : turn?.status === 'succeeded' && chat.session && (turn.text || turn.quote || turn.products.length > 0) &&
                    <LiveReply turn={turn} session={chat.session} onQuoteSaved={async () => {
                      if (chat.session) chat.record(await json<Turn>(turnPath(chat.session, turn.turn_id), chatRequest(chat.session)));
                    }} />}
                {message.role === 'assistant' && !message.author && latestHandoff?.turn_id === message.turn_id && chat.session &&
                  <SupportCard session={chat.session} support={latestHandoff.support} state={chat.handoff} refresh={chat.refresh} />}
              </div>;
            })}
            {unsyncedMessage && <p className="store-user-message store-turn">{unsyncedMessage.text}</p>}
            {chat.pending && !chat.pendingFailed && !chat.submitError && <p className="store-pending" role="status"><span aria-hidden="true"><i /><i /><i /></span> В обработке</p>}
          </div>
        ) : (
          <div className="store-chat-start">
            <h2>Здравствуйте! Чем помочь?</h2>
            <p>Опишите задачу или выберите вопрос, с которого хотите начать.</p>
            <div className="store-starters" aria-label="Примеры вопросов">
              {prompts.map(prompt => <button type="button" key={prompt.title} onClick={() => {
                setDraft(prompt.text); editor.current?.focus();
              }}><AppIcon name={prompt.icon} size={18} /> <span>{prompt.title}</span> <AppIcon name="chevron" size={14} /></button>)}
            </div>
          </div>
        )}
        <footer className="store-panel-footer">
          {chat.syncError && <p className="store-form-error" role="status">{chat.syncError}</p>}
          {!chat.sessionUnavailable && (chat.submitError || chat.pendingFailed) && <div className="store-send-retry" role="alert">
            <p>{chat.submitError || 'Помощник не смог завершить запрос.'}</p>
            {chat.pending && <button type="button" disabled={chat.busy} onClick={chat.retry}>Повторить отправку</button>}
          </div>}
          {closed && <p className="store-closed-note">Обращение закрыто. Для нового вопроса начните новый диалог.</p>}
          {!closed && !chat.sessionUnavailable && (
            <form className="store-composer" onSubmit={event => { event.preventDefault(); send(draft); }}>
              <label className="store-visually-hidden" htmlFor="live-store-question">Сообщение помощнику</label>
              <textarea id="live-store-question" ref={editor} rows={2} maxLength={8000} value={draft}
                placeholder={firstHandoff ? 'Напишите менеджеру…' : 'Напишите вопрос…'} onChange={event => setDraft(event.currentTarget.value)} onKeyDown={editorKeys} />
              <button type="submit" aria-label="Отправить сообщение" disabled={!draft.trim() || Boolean(chat.pending) || chat.loading}><AppIcon name="send" size={20} /></button>
            </form>
          )}
          <div className="store-footer-actions">
            {!firstHandoff && !chat.sessionUnavailable && <button type="button" disabled={Boolean(chat.pending) || chat.loading} onClick={() => send('Позовите менеджера')}><AppIcon name="support" size={16} /> Позвать менеджера</button>}
            {hasConversation && <button type="button" disabled={chat.busy || Boolean(chat.pending && !chat.submitError && !chat.pendingFailed && !chat.sessionUnavailable)} onClick={() => { chat.reset(); setDraft(''); }}>Новый диалог</button>}
          </div>
        </footer>
      </section>
    </main>
  );
}
