import { useEffect, useLayoutEffect, useRef } from 'react';
import type { KeyboardEvent } from 'react';
import { motion, useIsPresent, useReducedMotion } from 'motion/react';
import { AppIcon } from './AppIcon';
import { statuses } from './QueueAnalytics';
import { RequestTabContent } from './RequestInspector';
import type { OperatorRequest } from './operator-types';

export const requestPreviewId = 'journal-request-preview';

export function RequestStatus({ status }: { status: OperatorRequest['status'] }) {
  return <span className={`operator-status operator-status--${status}`}>{statuses.find(item => item.id === status)?.label}</span>;
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
  const { id, title, customer, issue, response } = request;
  const answer = response.messages.findLast(message => message.role === 'assistant');

  useEffect(() => {
    if (isPresent) card.current?.focus({ preventScroll: true });
  }, [isPresent]);

  useLayoutEffect(() => {
    if (body.current) body.current.scrollTop = 0;
    if (isPresent && !sideBySide) card.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [id, isPresent, sideBySide]);

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
      initial={{ opacity: 0, x: reduceMotion || !sideBySide ? 0 : 22, y: reduceMotion || sideBySide ? 0 : -8 }}
      animate={{ opacity: 1, x: 0, y: 0, transition: { duration: 0.27, ease: [0.2, 0.75, 0.25, 1], delay: reduceMotion ? 0 : 0.035 } }}
      exit={{ opacity: 0, x: reduceMotion || !sideBySide ? 0 : 14, transition: { duration: 0.17, ease: 'easeIn' } }}
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
          <div><span className="preview-id">{id}</span><RequestStatus status={request.status} /></div>
          <h2 id="request-preview-title">{title}</h2>
          <p>{customer}</p>
        </div>
        {issue && (
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
        <a href={href}>Полная карточка <AppIcon name="chevron" size={16} /></a>
      </footer>
    </motion.aside>
  );
}
