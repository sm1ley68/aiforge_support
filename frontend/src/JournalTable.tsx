import { useEffect, useLayoutEffect, useRef } from 'react';
import { motion, useIsPresent, useReducedMotion } from 'motion/react';
import { AppIcon } from './AppIcon';
import { statuses } from './QueueAnalytics';
import { RequestTabContent } from './RequestInspector';
import type { OperatorRequest } from './operator-types';

const timeZone = 'Europe/Moscow';
const clock = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone });
const calendar = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone });
const previewId = 'journal-request-preview';

function RequestStatus({ status }: { status: OperatorRequest['status'] }) {
  return <span className={`operator-status operator-status--${status}`}>{statuses.find(item => item.id === status)?.label}</span>;
}

export function JournalTable({ requests, selectedId, onOpen }: {
  requests: OperatorRequest[];
  selectedId?: string;
  onOpen: (id: string, trigger: HTMLButtonElement) => void;
}) {
  return (
    <table className="operator-table" aria-label="Список запросов" role="table">
      <thead role="rowgroup">
        <tr role="row">
          <th role="columnheader" scope="col">Запрос / компания</th>
          <th role="columnheader" scope="col">Причина проверки</th>
          <th role="columnheader" scope="col">Статус</th>
          <th role="columnheader" scope="col" aria-sort="descending">Обновлён</th>
        </tr>
      </thead>
      <tbody role="rowgroup">
        {requests.map(request => {
          const timestamp = Date.parse(request.updatedAt);
          const hasDate = Number.isFinite(timestamp);
          const reason = request.status === 'review' ? request.issue?.label : undefined;
          const selected = request.id === selectedId;
          return (
            <tr key={request.id} role="row" data-current={selected || undefined}>
              <td className="operator-title" role="cell">
                <button type="button" aria-expanded={selected} aria-controls={selectedId ? previewId : undefined} onClick={event => onOpen(request.id, event.currentTarget)}>{request.title}</button>
                <span>{request.customer}</span>
              </td>
              <td className="operator-reason" role="cell" data-empty={reason ? undefined : true}>{reason ?? '—'}</td>
              <td className="operator-row-status" role="cell"><RequestStatus status={request.status} /></td>
              <td className="operator-time" role="cell">
                {hasDate ? <time dateTime={request.updatedAt} title="Московское время">{clock.format(timestamp)}<small>{calendar.format(timestamp)}</small></time> : '—'}
                <AppIcon name="chevron" className="operator-row-arrow" size={16} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function RequestPreview({ request, href, position, total, onPrevious, onNext, onClose }: {
  request: OperatorRequest;
  href: string;
  position: number;
  total: number;
  onPrevious?: () => void;
  onNext?: () => void;
  onClose: () => void;
}) {
  const card = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const isPresent = useIsPresent();
  const reduceMotion = useReducedMotion();
  const sideBySide = window.matchMedia('(min-width: 1024px)').matches;
  const answer = request.response.messages.findLast(message => message.role === 'assistant');

  useEffect(() => {
    if (isPresent) card.current?.focus({ preventScroll: true });
  }, [isPresent]);

  useLayoutEffect(() => {
    if (body.current) body.current.scrollTop = 0;
    if (isPresent && !sideBySide) card.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [request.id, isPresent, sideBySide]);

  return (
    <motion.aside
      ref={card}
      id={previewId}
      className="request-preview"
      aria-labelledby="request-preview-title"
      tabIndex={-1}
      inert={!isPresent}
      initial={{ opacity: 0, x: reduceMotion || !sideBySide ? 0 : 22, y: reduceMotion || sideBySide ? 0 : -8 }}
      animate={{ opacity: 1, x: 0, y: 0, transition: { duration: 0.27, ease: [0.2, 0.75, 0.25, 1], delay: reduceMotion ? 0 : 0.035 } }}
      exit={{ opacity: 0, x: reduceMotion || !sideBySide ? 0 : 14, transition: { duration: 0.17, ease: 'easeIn' } }}
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose(); } }}
    >
      <header className="preview-toolbar">
        <span aria-live="polite" aria-atomic="true">{position} из {total}<span className="visually-hidden">. {request.title}</span></span>
        <div className="preview-controls">
          <div className="preview-navigation" role="group" aria-label="Просмотр запросов">
            <button type="button" aria-label="Предыдущий запрос" aria-disabled={!onPrevious} onClick={onPrevious}><AppIcon name="chevron" size={17} /></button>
            <button type="button" aria-label="Следующий запрос" aria-disabled={!onNext} onClick={onNext}><AppIcon name="chevron" size={17} /></button>
          </div>
          <button type="button" className="preview-close" aria-label="Закрыть запрос" onClick={onClose}><AppIcon name="close" size={19} /></button>
        </div>
      </header>
      <div className="request-preview-body" ref={body}>
        <div className="preview-heading">
          <div><span className="preview-id">{request.id}</span><RequestStatus status={request.status} /></div>
          <h2 id="request-preview-title">{request.title}</h2>
          <p>{request.customer}</p>
        </div>
        {request.issue && (
          <section className="preview-issue">
            <h3>{request.issue.label}</h3>
            <p>{request.issue.detail}</p>
            {Boolean(request.issue.checks?.length) && (
              <ul>{request.issue.checks?.map((check, index) => <li key={index}>{check}</li>)}</ul>
            )}
          </section>
        )}
        <section className="preview-answer">
          <h3>Ответ агента</h3>
          <p>{answer?.content ?? 'Агент пока не ответил.'}</p>
        </section>
        <section className="preview-sources">
          <h3>Источники <span>{request.response.sources.length}</span></h3>
          <RequestTabContent response={request.response} tab="sources" />
        </section>
      </div>
      <footer className="preview-footer">
        <a href={href}>Полная карточка <AppIcon name="chevron" size={16} /></a>
      </footer>
    </motion.aside>
  );
}
