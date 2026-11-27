import { useLayoutEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { AppIcon } from './AppIcon';
import { RequestMessages } from './RequestMessages';
import { ApiError, api, requestsUrl } from './softline-api';
import type { OperatorRequest, OperatorStatus } from './operator-types';

function actionError(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 401) return 'Сессия закончилась. Войдите в кабинет снова.';
  if (error.status === 409) return 'Запрос изменился. Проверьте новые сообщения и повторите.';
  return fallback;
}

function ArticleForm({ path, onPublished }: { path: string; onPublished: () => void }) {
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState('');

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const value = (name: string) => String(fields.get(name) ?? '').trim();
    setPublishing(true);
    setError('');
    try {
      await api(path, { method: 'POST', body: JSON.stringify({
        question: value('question'), answer: value('answer'), sourceUrl: value('source'),
        sku: value('sku') || null, publicContentConfirmed: fields.has('public'),
      }) });
      onPublished();
    } catch (error) {
      setError(error instanceof ApiError && error.status === 422
        ? 'Проверьте текст на личные данные и укажите публичную HTTPS-ссылку Softline без параметров.'
        : actionError(error, 'Не удалось опубликовать решение. Попробуйте ещё раз.'));
    } finally {
      setPublishing(false);
    }
  }

  return <form className="operator-live-form operator-article-form" onSubmit={publish}>
    <p>Агент сможет использовать эту статью в новых диалогах. Сформулируйте вопрос и ответ без данных клиента.</p>
    <label>Вопрос для статьи<input name="question" required minLength={3} maxLength={300} /></label>
    <label>Общий ответ<textarea name="answer" rows={4} required maxLength={4000} /></label>
    <label>Публичный источник<input name="source" type="url" required placeholder="https://docs.softline.com/…" /></label>
    <label>Артикул, если решение только для одного товара<input name="sku" maxLength={80} /></label>
    <label className="operator-article-check"><input name="public" type="checkbox" required /> Текст и источник можно показать другим клиентам</label>
    {error && <p className="chat-state-error" role="alert">{error}</p>}
    <button type="submit" className="operator-live-primary" disabled={publishing}>{publishing ? 'Публикуем…' : 'Опубликовать общее решение'}</button>
  </form>;
}

export function LiveManagerCase({ request, nextHref, reload }: {
  request: OperatorRequest; nextHref?: string; reload: () => void;
}) {
  const [draft, setDraft] = useState('');
  const [afterReply, setAfterReply] = useState<'resolved' | 'waiting'>('resolved');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  const [published, setPublished] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const pending = useRef<{ id: string; text: string; nextStatus: string; seenTurnId: string }>(undefined);
  const { response, handoffId, latestTurnId } = request;
  const actionPath = handoffId && `${requestsUrl.replace(/\/$/, '')}/${encodeURIComponent(handoffId)}`;
  const hasReply = sent || Boolean(request.managerRepliedAt);
  const count = response.messages.length;

  useLayoutEffect(() => {
    const element = transcript.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [count]);

  async function changeStatus(status: OperatorStatus) {
    if (!actionPath || !latestTurnId || busy || status === request.status) return;
    setBusy(true);
    setError('');
    try {
      await api(`${actionPath}/status`, { method: 'PUT', body: JSON.stringify({ status, seenTurnId: latestTurnId }) });
    } catch (error) {
      setError(actionError(error, 'Не удалось сохранить статус.'));
    } finally {
      reload();
      setBusy(false);
    }
  }

  async function reply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !actionPath || !latestTurnId || busy) return;
    let message = pending.current;
    if (!message || message.text !== text || message.nextStatus !== afterReply || message.seenTurnId !== latestTurnId) {
      message = { id: crypto.randomUUID(), text, nextStatus: afterReply, seenTurnId: latestTurnId };
      pending.current = message;
    }
    setBusy(true);
    setError('');
    try {
      await api(`${actionPath}/reply`, { method: 'POST', body: JSON.stringify({
        ...message, clientMessageId: message.id,
      }) });
      setSent(true);
      pending.current = undefined;
      setDraft('');
    } catch (error) {
      setError(actionError(error, 'Не удалось подтвердить отправку. Можно повторить с тем же текстом.'));
    } finally {
      reload();
      setBusy(false);
    }
  }

  return <div className="live-manager-case">
    <section className="request-chat" aria-label="Диалог с клиентом">
      <header className="request-chat-control">
        <div><AppIcon name="support" size={17} /><span>{request.status === 'resolved' ? 'Диалог закрыт' : 'Переписка с клиентом'}</span></div>
        {request.contactEmail && <a href={`mailto:${request.contactEmail}`}>{request.contactEmail}</a>}
      </header>
      <div ref={transcript} className="request-chat-transcript" role="log" aria-label="Переписка" tabIndex={0}>
        <RequestMessages messages={response.messages} />
      </div>
      {actionPath && request.status === 'review' && <form className="request-chat-compose" onSubmit={reply}>
        <div className="chat-compose-row chat-compose-row--text-only">
          <textarea ref={editor} aria-label="Сообщение клиенту" rows={1} maxLength={4000} required value={draft}
            placeholder="Ответить клиенту…" readOnly={busy}
            onChange={event => setDraft(event.currentTarget.value)}
            onKeyDown={event => {
              if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing ||
                window.matchMedia('(pointer: coarse)').matches) return;
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }} />
          <button className="chat-send" type="submit" aria-label="Ответить клиенту" title="Ответить клиенту" disabled={busy || !draft.trim()}>
            <AppIcon name="send" size={20} />
          </button>
        </div>
      </form>}
      <div className="request-workflow" role="group" aria-label="Действия с запросом">
        {request.needsReply && <button type="button" className="request-reply-action" onClick={() => editor.current?.focus()}>Ответить</button>}
        {actionPath && <label className="request-workflow-status operator-current-status" data-status={request.status}><span className="visually-hidden">Статус запроса</span>
          <select value={request.status} disabled={busy} onChange={event => void changeStatus(event.currentTarget.value as OperatorStatus)}>
            <option value="review">На проверке</option><option value="waiting">Ждём клиента</option><option value="resolved">Закрыт</option>
          </select>
        </label>}
        {actionPath && request.status === 'review' && <label className="request-workflow-status operator-reply-after">
          <span>После отправки</span>
          <select value={afterReply} disabled={busy} onChange={event => setAfterReply(event.currentTarget.value as typeof afterReply)}>
            <option value="resolved">Закрыть запрос</option><option value="waiting">Ждать ответа клиента</option>
          </select>
        </label>}
        <div className="request-workflow-next">{nextHref && !busy
          ? <a data-workspace-link href={nextHref}>Следующий запрос <AppIcon name="chevron" size={16} /></a>
          : <span>{busy ? 'Сохраняем…' : 'Других запросов на проверке нет'}</span>}</div>
      </div>
      {error && <p className="chat-state-error" role="alert">{error}</p>}
    </section>
    {actionPath && hasReply && <section className="operator-knowledge" aria-label="Общее решение">
      {request.articlePublished || published
        ? <p role="status"><AppIcon name="comparisonMatch" size={17} /> Общее решение опубликовано</p>
        : <details><summary>Опубликовать общее решение <AppIcon name="chevron" size={15} /></summary>
          <ArticleForm path={`${actionPath}/knowledge`} onPublished={() => { setPublished(true); reload(); }} /></details>}
    </section>}
  </div>;
}
