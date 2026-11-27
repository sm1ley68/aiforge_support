import { useEffect, useLayoutEffect, useRef } from 'react';
import type { KeyboardEvent } from 'react';
import { motion, useIsPresent, useReducedMotion } from 'motion/react';
import { AppIcon } from './AppIcon';
import { statuses } from './QueueAnalytics';
import { RequestTabContent } from './RequestInspector';
import type { OperatorRequest } from './operator-types';

export const requestPreviewId = 'journal-request-preview';

export function RequestStatus({ status, needsReply }: { status: OperatorRequest['status']; needsReply?: boolean }) {
  return <span className={`operator-status operator-status--${status}`}>{needsReply ? 'Ответить' : statuses.find(item => item.id === status)?.label}</span>;
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
  const { id, title, customer, issue, response } = request;
  const answer = response.messages.findLast(message => message.role === 'assistant');
  const customerReply = request.needsReply ? response.messages.findLast(message => message.role === 'user') : undefined;

  useEffect(() => {
    if (isPresent) card.current?.focus({ preventScroll: true });
  }, [isPresent]);

  useLayoutEffect(() => {
    if (body.current) body.current.scrollTop = 0;
  }, [id]);

  useLayoutEffect(() => {
    if (!isPresent || window.matchMedia('(min-width: 1024px)').matches) return;
    const frame = requestAnimationFrame(() => {
      const element = card.current;
      const desk = element?.closest('.operator-route');
      if (!element || !desk) return;
      const { top, bottom } = desk.getBoundingClientRect();
      const headerTop = element.getBoundingClientRect().top;
      if (headerTop < top || headerTop + 48 > bottom) {
        element.scrollIntoView({ block: 'start', inline: 'nearest', behavior: reduceMotion ? 'instant' : 'smooth' });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [isPresent, reduceMotion]);

  function closeOnEscape(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    onClose();
  }

  return (
    <motion.aside
      ref={card}
      id={requestPreviewId}
      className="request-preview"
      aria-labelledby="request-preview-title"
      tabIndex={-1}
      inert={!isPresent}
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : .27, ease: [0.22, 0.75, 0.26, 1], delay: reduceMotion ? 0 : .026 } }}
      exit={{ opacity: 0, y: reduceMotion ? 0 : -4, transition: { duration: reduceMotion ? 0 : .15, ease: 'easeOut' } }}
      onKeyDown={closeOnEscape}
    >
      <header className="preview-toolbar">
        <span aria-live="polite" aria-atomic="true">{position} из {total}<span className="visually-hidden">. {title}</span></span>
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
          <div><span className="preview-id">{id}</span><RequestStatus status={request.status} needsReply={request.needsReply} /></div>
          <h2 id="request-preview-title">{title}</h2>
          <p>{customer}</p>
        </div>
        {customerReply ? (
          <section className="preview-issue">
            <h3>Клиент ответил</h3>
            <p>{customerReply.content}</p>
          </section>
        ) : issue && (
          <section className="preview-issue">
            <h3>{issue.label}</h3>
            <p>{issue.detail}</p>
            {Boolean(issue.checks?.length) && (
              <ul>{issue.checks?.map((check, index) => <li key={index}>{check}</li>)}</ul>
            )}
          </section>
        )}
        <section className="preview-answer">
          <h3>Ответ агента</h3>
          <p>{answer?.content ?? 'Агент пока не ответил.'}</p>
        </section>
        <section className="preview-sources">
          <h3>Источники <span>{response.sources.length}</span></h3>
          <RequestTabContent response={response} tab="sources" />
        </section>
      </div>
      <footer className="preview-footer">
        <a data-workspace-link data-opened-from-journal href={href}>Полная карточка <AppIcon name="chevron" size={16} /></a>
      </footer>
    </motion.aside>
  );
}
