import { useEffect, useRef, useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { AgentTestDialog } from './AgentTestDialog';
import { AppIcon } from './AppIcon';
import { JournalTable } from './JournalTable';
import { OperatorRoutePane } from './OperatorRoutePane';
import { QueueFeedback, QueueSearch, filterRequests, requestsToReview, reviewReason } from './QueueControls';
import { statuses } from './QueueAnalytics';
import { QueueDashboard } from './QueueDashboard';
import { RailButton } from './RailButton';
import { RequestPreview } from './RequestPreview';
import { SelectedRequest } from './RequestViews';
import { journalHref, useOperatorNavigation, workspaceHref } from './use-operator-navigation';
import { useOperatorQueue } from './use-operator-queue';
import { customerChatView } from './store-advisor-demo';

export function OperatorWorkspace() {
  const { route, desk, filter, setFilter, query, setQuery, previewId, setPreviewId, navigate } = useOperatorNavigation();
  const params = new URLSearchParams(route.search);
  const requestId = params.get('request');
  const isJournal = requestId === null && (params.get('view') === 'journal' || params.has('status') || params.has('issue'));
  const isDashboard = requestId === null && !isJournal;
  const { requests, loading, error, reload, changeStatus } = useOperatorQueue();
  const [testing, setTesting] = useState(false);
  const previewTrigger = useRef<HTMLButtonElement>(null);
  const closedPreviewTrigger = useRef<HTMLButtonElement>(null);
  const request = requests.find(item => item.id === requestId);
  const reviewQueue = request ? requestsToReview(requests) : [];
  const title = isDashboard ? 'Дашборд' : isJournal ? 'Журнал запросов' : request?.title ?? 'Запрос';

  useEffect(() => {
    document.title = `${title} | Softline Store`;
  }, [title]);

  const feedback = <QueueFeedback loading={loading} error={error} reload={reload} />;
  const counts = { review: 0, waiting: 0, resolved: 0 };
  const issueCounts = new Map<string, number>();
  let sourcedCount = 0;
  for (const item of requests) {
    counts[item.status] += 1;
    if (item.response.sources.length) sourcedCount += 1;
    const label = reviewReason(item);
    if (item.status === 'review' && label) {
      issueCounts.set(label, (issueCounts.get(label) ?? 0) + 1);
    }
  }
  const issues = [...issueCounts].sort(([, first], [, second]) => second - first);
  const filtered = isJournal ? filterRequests(requests, filter, query) : [];
  const previewIndex = filtered.findIndex(item => item.id === previewId);
  const preview = filtered[previewIndex];
  const allRequests = !filter.status && !filter.issue;
  const hasQuery = Boolean(query.trim());
  const showCounts = !loading && !error;

  useEffect(() => {
    if (previewId && !preview) setPreviewId(undefined);
  }, [preview, previewId, setPreviewId]);

  function closePreview() {
    const trigger = previewTrigger.current?.isConnected
      ? previewTrigger.current
      : desk.current?.querySelector<HTMLButtonElement>('.operator-table tr[data-current] button');
    closedPreviewTrigger.current = trigger ?? null;
    setPreviewId(undefined);
    trigger?.focus({ preventScroll: true });
  }

  function openPreview(id: string, trigger: HTMLButtonElement) {
    closedPreviewTrigger.current = null;
    previewTrigger.current = trigger;
    setPreviewId(id);
  }

  function restorePreviewScroll() {
    const trigger = closedPreviewTrigger.current;
    closedPreviewTrigger.current = null;
    if (!trigger?.isConnected || !desk.current?.contains(trigger) || window.matchMedia('(min-width: 1024px)').matches) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    trigger.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: reduced ? 'instant' : 'smooth' });
  }

  return (
    <main className={`stage stage--ascii stage--operator${isDashboard ? ' stage--dashboard' : ''}`} onClick={navigate}>
      <div className="workspace workspace--nav-mono">
        <nav className="rail rail--mono" aria-label="Навигация сотрудника">
          <span className="rail-emblem" aria-hidden="true"><AppIcon name="mark" size={20} /></span>
          <div className="rail-middle">
            <a data-workspace-link className="rail-button" href={workspaceHref()} title="Дашборд" aria-label="Дашборд" aria-current={isDashboard ? 'page' : undefined}><AppIcon name="chart" size={20} /></a>
            <a data-workspace-link className="rail-button" href={journalHref()} title="Журнал запросов" aria-label="Журнал запросов" aria-current={isJournal ? 'page' : undefined}><AppIcon name="journal" size={20} /></a>
          </div>
          <div className="rail-utilities">
            <a className="rail-button" href={customerChatView} title="Клиентский чат" aria-label="Клиентский чат"><AppIcon name="agent" size={20} /></a>
            <RailButton icon="test" title="Тест агента" onClick={() => setTesting(true)} />
          </div>
        </nav>

        <AnimatePresence initial={!isDashboard}>
          <OperatorRoutePane key={route.entryId} activeDesk={desk} scrollTop={route.scrollTop} moved={route.moved}>
            {isDashboard ? (
              <QueueDashboard
                requests={requests}
                counts={counts}
                sourcedCount={sourcedCount}
                issues={issues}
                loading={loading}
                error={error}
                reload={reload}
                journalHref={journalHref}
                requestHref={id => workspaceHref({ request: id })}
              />
            ) : isJournal ? (
              <section className="workspace-screen journal-screen" data-preview-open={Boolean(preview)} aria-labelledby="journal-title">
                <header className="screen-heading journal-top">
                  <div><span className="journal-wordmark">Softline Store</span><h1 id="journal-title">Журнал запросов</h1></div>
                  {showCounts && requests.length > 0 && (
                    <p className="journal-coverage"><AppIcon name="sources" size={17} /> Запросы с источниками <strong>{sourcedCount} из {requests.length}</strong></p>
                  )}
                </header>
                <div className="journal-columns">
                  <div className="queue operator-queue" aria-busy={loading}>
                    <div className="journal-tools">
                      <div className="journal-filters" role="group" aria-label="Запросы по статусу">
                        <button type="button" aria-pressed={allRequests} onClick={() => setFilter({})}>
                          Все <b>{showCounts ? requests.length : '—'}</b>
                        </button>
                        {statuses.map(status => (
                          <button type="button" key={status.id} aria-pressed={filter.status === status.id} onClick={() => setFilter({ status: status.id })}>
                            {status.label} <b>{showCounts ? counts[status.id] : '—'}</b>
                          </button>
                        ))}
                      </div>
                      <QueueSearch query={query} onQuery={setQuery} />
                    </div>
                    {showCounts && (issues.length > 0 || filter.issue) && (
                      <div className="reason-filters" role="group" aria-label="Причины ручной проверки">
                        <span className="reason-label"><AppIcon name="filter" size={15} /> Причина проверки</span>
                        {issues.map(([issue, count]) => (
                          <button type="button" key={issue} aria-pressed={filter.issue === issue} onClick={() => setFilter({ status: 'review', issue: filter.issue === issue ? undefined : issue })}>
                            {issue} <b>{count}</b>
                          </button>
                        ))}
                        {filter.issue && !issueCounts.has(filter.issue) && (
                          <button type="button" aria-pressed="true" onClick={() => setFilter({ status: 'review' })}>{filter.issue} <AppIcon name="close" size={13} /></button>
                        )}
                      </div>
                    )}
                    {feedback}
                    {showCounts && (
                      <>
                        <JournalTable requests={filtered} selectedId={preview?.id} onOpen={openPreview} />
                        {filtered.length === 0 && (
                          <div className="queue-empty">
                            <p>{hasQuery || !allRequests ? 'Запросы не найдены' : 'Журнал пока пуст'}</p>
                            {(hasQuery || !allRequests) && <button type="button" onClick={() => { setQuery(''); setFilter({}); }}>Сбросить фильтры</button>}
                          </div>
                        )}
                        <footer className="journal-count" role="status">Показано <strong>{filtered.length}</strong> из {requests.length}</footer>
                      </>
                    )}
                  </div>
                  <div className="journal-preview-slot">
                    <AnimatePresence initial={false} onExitComplete={restorePreviewScroll}>
                      {preview && (
                        <RequestPreview
                          key="request-preview"
                          request={preview}
                          href={workspaceHref({ request: preview.id })}
                          position={previewIndex + 1}
                          total={filtered.length}
                          onPrevious={previewIndex > 0 ? () => setPreviewId(filtered[previewIndex - 1].id) : undefined}
                          onNext={previewIndex < filtered.length - 1 ? () => setPreviewId(filtered[previewIndex + 1].id) : undefined}
                          onClose={closePreview}
                        />
                      )}
                    </AnimatePresence>
                  </div>
                </div>
              </section>
            ) : (
              <section className="workspace-screen request-screen" aria-label="Запрос">
                <header className="screen-heading">
                  <a data-workspace-link data-return-to-journal className="screen-link" href={journalHref()}><AppIcon name="back" size={17} />К журналу</a>
                </header>
                <div className="request-detail">
                  {request ? (
                    <SelectedRequest key={request.id} request={request} reviewQueue={reviewQueue}
                      requestHref={id => workspaceHref({ request: id })}
                      changeStatus={changeStatus && (status => changeStatus(request, status))} />
                  ) : (
                    <div className="request-unavailable">
                      <h1>Запрос</h1>
                      {feedback}
                      {!loading && !error && <p>Запрос не найден в журнале.</p>}
                    </div>
                  )}
                </div>
              </section>
            )}
          </OperatorRoutePane>
        </AnimatePresence>
      </div>

      {testing && <AgentTestDialog onClose={() => setTesting(false)} />}
    </main>
  );
}
