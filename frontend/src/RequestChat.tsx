import { useLayoutEffect, useRef, useState } from 'react';
import { AppIcon } from './AppIcon';
import { fileSize, RequestMessages, type TranscriptMessage } from './RequestMessages';
import type { OperatorRequest, OperatorStatus } from './operator-types';
import { attachmentBytesLimit, attachmentLimit, type RequestChatState } from './use-request-chat';

export function RequestChat({ request, chat, nextHref, changeStatus }: {
  request: OperatorRequest;
  chat: RequestChatState;
  nextHref?: string;
  changeStatus?: (status: OperatorStatus) => Promise<unknown>;
}) {
  const seed = request.response.messages;
  const { ready, taken, taking, draft, pending, error, storageWarning, send, setDraft } = chat;
  const [attachmentError, setAttachmentError] = useState('');
  const [statusError, setStatusError] = useState('');
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const focusAfterTakeover = useRef(false);
  const transcript = useRef<HTMLDivElement>(null);
  const closed = Boolean(changeStatus) && request.status === 'resolved';
  const busy = updatingStatus || taking || Boolean(pending);
  const blocked = !ready || !taken || closed || busy;
  const canSend = !blocked && Boolean(draft.text.trim() || draft.files.length);
  const latestCustomerMessage = seed.findLast(message => message.role === 'user');
  const recordedIds = new Set(seed.flatMap(message => [message.id, message.clientMessageId].filter(Boolean)));
  const messages: TranscriptMessage[] = [
    ...seed,
    ...chat.messages.filter(message => !recordedIds.has(message.id)).map(({ id, draft, sentAt }): TranscriptMessage => (
      { id, role: 'support', mine: true, content: draft.text, files: draft.files, sentAt }
    )),
  ];
  if (pending && !messages.some(message => (message.clientMessageId ?? message.id) === pending.id)) {
    messages.push({ id: pending.id, role: 'support', mine: true, content: pending.draft.text, files: pending.draft.files, sentAt: pending.sentAt });
  }
  if (chat.demo) messages.sort((first, second) => (first.sentAt ?? 0) - (second.sentAt ?? 0));

  useLayoutEffect(() => {
    const element = transcript.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [seed, chat.messages, pending, taken]);

  useLayoutEffect(() => {
    if (!focusAfterTakeover.current || taking || !taken) return;
    focusAfterTakeover.current = false;
    focusComposer();
  }, [taken, taking]);

  function focusComposer() {
    const field = textarea.current;
    field?.focus({ preventScroll: true });
    field?.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }

  function beginReply() {
    if (taken) {
      focusComposer();
    } else {
      focusAfterTakeover.current = true;
      void chat.takeOver();
    }
  }

  async function updateStatus(status: OperatorStatus) {
    if (!changeStatus || busy || status === request.status) return;
    setUpdatingStatus(true);
    setStatusError('');
    try {
      await changeStatus(status);
    } catch {
      setStatusError('Не удалось сохранить статус. Попробуйте ещё раз.');
    } finally {
      setUpdatingStatus(false);
    }
  }

  function addFiles(newFiles: FileList) {
    if (blocked || !newFiles.length) return;

    const files = [...draft.files, ...Array.from(newFiles)];
    if (files.length > attachmentLimit || files.reduce((total, file) => total + file.size, 0) > attachmentBytesLimit) {
      setAttachmentError(`Можно прикрепить до ${attachmentLimit} файлов общим размером до ${fileSize(attachmentBytesLimit)}.`);
      return;
    }

    setAttachmentError('');
    setDraft({ ...draft, files });
  }

  return (
    <section className="request-chat" aria-label="Диалог с клиентом">
      <header className="request-chat-control">
        <div>
          <AppIcon name={taken ? 'support' : 'agent'} size={17} />
          <span>{taken ? 'Вы ведёте диалог' : 'Агент Store ведёт диалог'}{chat.demo && <small>Деморежим</small>}</span>
        </div>
        {!taken && !closed && (
          <button type="button" className="chat-take-over" disabled={!ready || busy} onClick={beginReply}>
            {taking ? 'Передача диалога…' : 'Взять в работу'}
          </button>
        )}
      </header>
      <div ref={transcript} className="request-chat-transcript" role="log" aria-label="Переписка" tabIndex={0}>
        <RequestMessages messages={messages} />
        {pending && <p className="chat-sending" role="status"><AppIcon name="loading" className="spinner" size={15} /> Отправка сообщения…</p>}
        {!ready && <p className="chat-sending" role="status">Загрузка истории…</p>}
      </div>
      {!taken && error && <p className="chat-state-error" role="alert">{error}</p>}
      {closed && <p className="chat-closed-note">Запрос закрыт. Чтобы ответить, верните его на проверку.</p>}
      {taken && !closed && (
        <form
          className="request-chat-compose"
          data-dragging={dragging || undefined}
          onSubmit={event => { event.preventDefault(); if (canSend) { setAttachmentError(''); void send(latestCustomerMessage?.id); } }}
          onDragEnter={event => {
            if (!event.dataTransfer.types.includes('Files')) return;
            event.preventDefault();
            dragDepth.current += 1;
            if (!blocked) setDragging(true);
          }}
          onDragOver={event => {
            if (!event.dataTransfer.types.includes('Files')) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = blocked ? 'none' : 'copy';
          }}
          onDragLeave={() => {
            dragDepth.current = Math.max(0, dragDepth.current - 1);
            if (!dragDepth.current) setDragging(false);
          }}
          onDrop={event => {
            if (!event.dataTransfer.types.includes('Files')) return;
            event.preventDefault();
            dragDepth.current = 0;
            setDragging(false);
            addFiles(event.dataTransfer.files);
          }}
        >
          {draft.files.length > 0 && (
            <ul className="chat-files chat-draft-files" aria-label="Файлы к отправке">
              {draft.files.map((file, index) => (
                <li className="chat-file" key={index}>
                  <AppIcon name="attach" size={16} />
                  <span><strong>{file.name}</strong><small>{fileSize(file.size)}</small></span>
                  <button type="button" className="chat-file-remove" aria-label={`Убрать ${file.name}`} onClick={() => {
                    setAttachmentError('');
                    setDraft({ ...draft, files: draft.files.filter((_, position) => position !== index) });
                  }}><AppIcon name="close" size={15} /></button>
                </li>
              ))}
            </ul>
          )}
          <div className="chat-compose-row">
            <input
              ref={input}
              type="file"
              aria-label="Вложения"
              hidden
              multiple
              onChange={event => {
                if (event.currentTarget.files) addFiles(event.currentTarget.files);
                event.currentTarget.value = '';
              }}
            />
            <button type="button" className="chat-attach" aria-label="Прикрепить файлы" title="Прикрепить файлы" disabled={blocked} onClick={() => input.current?.click()}>
              <AppIcon name="attach" size={20} />
            </button>
            <textarea
              ref={textarea}
              aria-label="Сообщение клиенту"
              rows={1}
              placeholder="Ответить клиенту…"
              value={draft.text}
              readOnly={blocked}
              onChange={event => setDraft({ ...draft, text: event.currentTarget.value })}
              onKeyDown={event => {
                if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }}
              onPaste={event => {
                if (!event.clipboardData.files.length) return;
                if (!event.clipboardData.getData('text/plain')) event.preventDefault();
                addFiles(event.clipboardData.files);
              }}
            />
            <button type="submit" className="chat-send" aria-label="Отправить сообщение" title="Отправить сообщение" disabled={!canSend}>
              <AppIcon name="send" size={20} />
            </button>
          </div>
          {(attachmentError || error) && <p className="chat-error" role="alert">{attachmentError || error}</p>}
          {storageWarning && <p className="chat-storage-warning" role="status">{storageWarning}</p>}
        </form>
      )}
      <div className="request-workflow" aria-label="Действия с запросом">
        {request.needsReply && (
          <button className="request-reply-action" disabled={!ready || busy} type="button" onClick={beginReply}>Ответить</button>
        )}
        {changeStatus && (
          <label className="request-workflow-status">
            <span className="visually-hidden">Статус запроса</span>
            <select value={request.status} disabled={busy} onChange={event => void updateStatus(event.currentTarget.value as OperatorStatus)}>
              <option value="review">На проверке</option>
              <option value="waiting">Ждём клиента</option>
              <option value="resolved">Закрыт</option>
            </select>
          </label>
        )}
        <div className="request-workflow-next">
          {nextHref && !busy ? (
            <a data-workspace-link href={nextHref}>Следующий <AppIcon name="chevron" size={16} /></a>
          ) : (
            <span role="status">{busy ? 'Сохраняем…' : 'Других запросов на проверке нет'}</span>
          )}
        </div>
      </div>
      {statusError && <p className="chat-state-error" role="alert">{statusError}</p>}
    </section>
  );
}
