import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type Ref } from 'react';
import { useReducedMotion } from 'motion/react';
import { AppIcon } from './AppIcon';
import { QueueActivityChart } from './QueueActivityChart';
import { QueueFeedback, filterRequests, requestsToReview, requestTimestamp, reviewReason } from './QueueControls';
import type { QueueFilter } from './QueueControls';
import { RequestStatus } from './RequestPreview';
import type { OperatorRequest, OperatorStatus } from './operator-types';

const previewLimit = 5;
const timeZone = 'Europe/Moscow';
const clock = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone });
const calendar = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone });
const numberFormat = new Intl.NumberFormat('ru-RU');
const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });
type QueueView = 'review' | 'recent';

function inactivity(elapsed: number) {
  const minutes = Math.floor(elapsed / 60_000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days) return `${days} д ${hours % 24} ч`;
  if (hours) return `${hours} ч ${minutes % 60} мин`;
  return `${minutes} мин`;
}

function DashboardReviewCard({ request, href, headingRef, isReviewView }: {
  request?: OperatorRequest;
  href?: string;
  headingRef: Ref<HTMLHeadingElement>;
  isReviewView: boolean;
}) {
  const review = request?.status === 'review';
  const checks = review && !request?.needsReply ? request?.issue?.checks?.slice(0, 2) : undefined;
  const description = request?.needsReply
    ? request.response.messages.findLast(message => message.role === 'user')?.content
    : review
    ? request?.issue?.detail || 'Причина проверки пока не указана.'
    : request?.response.reply || request?.response.messages.findLast(message => message.role === 'assistant')?.content;

  return (
    <section className="dashboard-review-card" id="dashboard-selected-request" aria-labelledby="dashboard-selected-title">
      <header className="dashboard-section-heading">
        <h2 id="dashboard-selected-title" tabIndex={-1} ref={headingRef}>
          {review || !request && isReviewView ? 'Что проверить сейчас' : 'Выбранный запрос'}
        </h2>
      </header>
      {request ? (
        <div className="dashboard-review-content" key={request.id}>
          <div className="dashboard-review-meta">
            <RequestStatus status={request.status} needsReply={request.needsReply} />
            <span>{request.id}</span>
          </div>
          <h3>{request.title}</h3>
          {checks?.length ? (
            <ul className="dashboard-review-checks">
              {checks.map((check, index) => <li key={`${index}-${check}`}>{check}</li>)}
            </ul>
          ) : null}
          {description && <p className="dashboard-review-description">{description}</p>}
          {href && (
            <a data-workspace-link className="dashboard-review-open" href={href}>
              Открыть запрос <AppIcon name="chevron" size={15} />
            </a>
          )}
        </div>
      ) : (
        <p className="dashboard-empty">{isReviewView ? 'Очередь на проверку пуста.' : 'В журнале пока нет запросов.'}</p>
      )}
    </section>
  );
}

export function QueueDashboard({ requests, counts, sourcedCount, issues, loading, error, reload, journalHref, requestHref }: {
  requests: OperatorRequest[];
  counts: Record<OperatorStatus, number>;
  sourcedCount: number;
  issues: [string, number][];
  loading: boolean;
  error: string;
  reload: () => void;
  journalHref: (filter?: QueueFilter) => string;
  requestHref: (id: string) => string;
}) {
  const [view, setView] = useState<QueueView>('review');
  const [selectedRequestId, setSelectedRequestId] = useState<string>();
  const [now, setNow] = useState(Date.now);
  const [hoveredIssue, setHoveredIssue] = useState<string>();
  const [focusedIssue, setFocusedIssue] = useState<string>();
  const queueBody = useRef<HTMLDivElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const previousQueueHeight = useRef<number | undefined>(undefined);
  const reducedMotion = useReducedMotion();
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useLayoutEffect(() => {
    const from = previousQueueHeight.current;
    previousQueueHeight.current = undefined;
    const body = queueBody.current;
    if (reducedMotion || from === undefined || !body) return;
    const to = body.getBoundingClientRect().height;
    if (Math.abs(to - from) < 1) return;

    const animation = body.animate([{ height: `${from}px` }, { height: `${to}px` }], {
      duration: 260,
      easing: 'cubic-bezier(.19, 1, .22, 1)',
    });
    return () => animation.cancel();
  }, [reducedMotion, view]);

  function changeView(next: QueueView) {
    if (next === view) return;
    previousQueueHeight.current = reducedMotion ? undefined : queueBody.current?.getBoundingClientRect().height;
    setSelectedRequestId(undefined);
    setView(next);
  }

  function selectRequest(id: string) {
    setSelectedRequestId(id);
    if (!window.matchMedia('(max-width: 760px)').matches) return;
    const heading = reviewHeading.current;
    heading?.focus({ preventScroll: true });
    heading?.scrollIntoView({ block: 'start', inline: 'nearest', behavior: reducedMotion ? 'instant' : 'smooth' });
  }

  const isReview = view === 'review';
  const highlightedIssue = hoveredIssue ?? focusedIssue;
  const reviewQueue = requestsToReview(requests);
  const queue = isReview ? reviewQueue : filterRequests(requests, {}, '');
  const visible = queue.slice(0, previewLimit);
  const selectedRequest = visible.find(request => request.id === selectedRequestId) ?? visible[0];
  const oldest = reviewQueue.reduce<OperatorRequest | undefined>((earliest, request) =>
    !earliest || requestTimestamp(request) < requestTimestamp(earliest) ? request : earliest, undefined);
  const oldestUpdate = oldest ? requestTimestamp(oldest) : Infinity;
  const total = requests.length;
  const reviewShare = total ? counts.review / total : 0;
  const recommended = requests.filter(request => request.response.products.some(product => product.recommended)).length;

  return (
    <section className="workspace-screen dashboard-screen" aria-labelledby="dashboard-title" aria-busy={loading}>
      <header className="dashboard-header">
        <div>
          <p className="dashboard-brand">Softline Store</p>
          <h1 id="dashboard-title">Дашборд</h1>
        </div>
        <a data-workspace-link className="dashboard-journal-link" href={journalHref()}>
          <AppIcon name="journal" size={17} /> Журнал запросов <AppIcon name="chevron" size={14} />
        </a>
      </header>

      {loading || error ? (
        <div className="dashboard-panel dashboard-feedback"><QueueFeedback loading={loading} error={error} reload={reload} /></div>
      ) : (
        <>
          <ul className="dashboard-panel dashboard-kpis" aria-label="Состояние очереди">
            <li className="dashboard-kpi-primary">
              <a data-workspace-link className="dashboard-kpi" data-tone="review" href={journalHref({ status: 'review' })}>
                <strong className="dashboard-review-count">
                  <span aria-hidden="true" style={{ '--dashboard-review-progress': `${reviewShare * 100}%` } as CSSProperties} />
                  {numberFormat.format(counts.review)}
                </strong>
                <span>На ручную проверку</span>
                <small>{total ? `${percent.format(reviewShare)} всех запросов` : 'Журнал пуст'}</small>
                <AppIcon name="chevron" className="dashboard-kpi-arrow" size={16} />
              </a>
            </li>
            <li>
              {oldest && oldestUpdate <= now ? (
                <a data-workspace-link className="dashboard-kpi" href={requestHref(oldest.id)}>
                  <span>Дольше без обновления</span>
                  <strong>{inactivity(now - oldestUpdate)}</strong>
                  <small>Среди запросов на проверке</small>
                  <AppIcon name="chevron" className="dashboard-kpi-arrow" size={14} />
                </a>
              ) : (
                <div className="dashboard-kpi">
                  <span>Дольше без обновления</span>
                  <strong>—</strong>
                  <small>Среди запросов на проверке</small>
                </div>
              )}
            </li>
            <li className="dashboard-kpi">
              <span>Открытые запросы</span>
              <strong>{numberFormat.format(counts.review + counts.waiting)}</strong>
              <small>{numberFormat.format(counts.waiting)} ждут клиента · {numberFormat.format(total)} всего</small>
            </li>
          </ul>

          <div className="dashboard-review-layout">
            <div className="dashboard-panel dashboard-main">
              <section className="dashboard-panel dashboard-recent" aria-labelledby="dashboard-requests-title">
                <header className="dashboard-section-heading dashboard-requests-heading">
                  <h2 id="dashboard-requests-title">{isReview ? 'Очередь на проверку' : 'Последние обновления'}</h2>
                  <div className="dashboard-views dashboard-review-tabs" data-view={view} data-second={!isReview || undefined} role="group" aria-label="Список запросов">
                    <button type="button" aria-pressed={isReview} onClick={() => changeView('review')}><AppIcon name="review" size={14} />На проверку</button>
                    <button type="button" aria-pressed={!isReview} onClick={() => changeView('recent')}><AppIcon name="journal" size={14} />Последние</button>
                  </div>
                </header>
                <div className="dashboard-queue-body" ref={queueBody}>
                  {visible.length ? (
                    <>
                      <div className="dashboard-request-head" aria-hidden="true">
                        <span>Запрос / компания</span>
                        <span>{isReview ? 'Причина проверки' : 'Статус'}</span>
                        <span>Обновлён{isReview ? reviewQueue.some(item => item.needsReply) ? '' : ' ↑' : ' ↓'}</span>
                      </div>
                      <ul key={view} className="dashboard-list dashboard-requests">
                        {visible.map(request => {
                          const timestamp = requestTimestamp(request);
                          const reason = reviewReason(request);
                          return (
                            <li className="dashboard-request-row" key={request.id}
                              data-selected={request.id === selectedRequest?.id || undefined}
                              data-related={isReview && Boolean(reason) && reason === highlightedIssue || undefined}
                            >
                              <button
                                type="button"
                                className="dashboard-request-select"
                                aria-pressed={request.id === selectedRequest?.id}
                                aria-controls="dashboard-selected-request"
                                onClick={() => selectRequest(request.id)}
                              >
                                <span className="dashboard-request-copy"><strong>{request.title}</strong><small>{request.customer}</small></span>
                                <span className="dashboard-request-context">
                                  {isReview ? reason || 'Причина не указана' : <RequestStatus status={request.status} needsReply={request.needsReply} />}
                                </span>
                                <span className="dashboard-time">
                                  {Number.isFinite(timestamp) ? (
                                    <time dateTime={request.updatedAt} title="Московское время">{clock.format(timestamp)}<small>{calendar.format(timestamp)}</small></time>
                                  ) : '—'}
                                </span>
                              </button>
                              <a data-workspace-link className="dashboard-request-open" href={requestHref(request.id)}
                                aria-label={`Открыть запрос «${request.title}»`} title="Открыть запрос"
                              >
                                <AppIcon name="chevron" size={16} />
                              </a>
                            </li>
                          );
                        })}
                      </ul>
                      {queue.length > previewLimit && (
                          <a data-workspace-link className="dashboard-list-more" href={journalHref(isReview ? { status: 'review' } : {})}>
                          {isReview ? 'Вся очередь на проверку' : 'Все запросы'} <AppIcon name="chevron" size={15} />
                        </a>
                      )}
                    </>
                  ) : <p className="dashboard-empty">{isReview ? 'Нет запросов на проверку.' : 'Журнал пока пуст.'}</p>}
                </div>
              </section>
              <QueueActivityChart requests={requests} journalHref={journalHref} />
            </div>

            <aside className="dashboard-panel dashboard-sidebar" aria-label="Проверка запросов">
              <DashboardReviewCard request={selectedRequest} href={selectedRequest && requestHref(selectedRequest.id)}
                headingRef={reviewHeading} isReviewView={isReview} />
              <section className="dashboard-details" aria-labelledby="dashboard-issues-title">
                <header className="dashboard-section-heading">
                  <h2 id="dashboard-issues-title">Причины проверки</h2>
                </header>
                {issues.length ? (
                  <ul className="dashboard-list dashboard-issues">
                    {issues.map(([issue, count]) => (
                      <li key={issue}>
                        <a
                          data-workspace-link
                          className="dashboard-issue-link"
                          href={journalHref({ status: 'review', issue })}
                          onPointerEnter={event => { if (event.pointerType !== 'touch') setHoveredIssue(issue); }}
                          onPointerLeave={() => setHoveredIssue(undefined)}
                          onFocus={() => setFocusedIssue(issue)}
                          onBlur={() => setFocusedIssue(undefined)}
                        >
                          <span className="dashboard-issue-name">{issue}</span>
                          <strong>{numberFormat.format(count)}</strong>
                        </a>
                      </li>
                    ))}
                  </ul>
                ) : <p className="dashboard-empty">Нет отмеченных причин проверки.</p>}
              </section>

              <section className="dashboard-quality" aria-labelledby="dashboard-quality-title">
                <header className="dashboard-section-heading"><h2 id="dashboard-quality-title">Результаты агента</h2></header>
                <dl className="dashboard-quality-metrics">
                  <div>
                    <dt>Запросы с источниками</dt>
                    <dd>
                      <strong>{total ? percent.format(sourcedCount / total) : '—'}</strong>
                      <small>{numberFormat.format(sourcedCount)} из {numberFormat.format(total)} запросов</small>
                    </dd>
                  </div>
                  <div>
                    <dt>С рекомендацией агента</dt>
                    <dd>
                      <strong>{total ? percent.format(recommended / total) : '—'}</strong>
                      <small>{numberFormat.format(recommended)} из {numberFormat.format(total)} запросов</small>
                    </dd>
                  </div>
                </dl>
              </section>
            </aside>
          </div>
        </>
      )}
    </section>
  );
}
