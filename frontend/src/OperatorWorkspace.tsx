import { useEffect, useRef, useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { AgentTestDialog } from './AgentTestDialog';
import { AppIcon } from './AppIcon';
import { JournalTable } from './JournalTable';
import { QueueFeedback, QueueSearch, filterRequests } from './QueueControls';
import type { QueueFilter } from './QueueControls';
import { statuses } from './QueueAnalytics';
import { RailButton } from './RailButton';
import { RequestPreview } from './RequestPreview';
import { SelectedRequest } from './RequestViews';
import { useOperatorQueue } from './use-operator-queue';

function workspaceHref(route: Record<string, string> = {}) {
  const url = new URL(window.location.href);
  for (const key of ['view', 'status', 'issue', 'request']) url.searchParams.delete(key);
  for (const [key, value] of Object.entries(route)) url.searchParams.set(key, value);
  return url.pathname + url.search;
}

export function OperatorWorkspace() {
  const params = new URLSearchParams(window.location.search);
  const requestId = params.get('request');
  const isJournal = requestId === null;
  const { requests, loading, error, reload } = useOperatorQueue();
  const [testing, setTesting] = useState(false);
  const [query, setQuery] = useState('');
  const [previewId, setPreviewId] = useState<string>();
  const previewTrigger = useRef<HTMLButtonElement>(null);
  const [filter, setFilter] = useState<QueueFilter>(() => ({
    status: statuses.find(status => status.id === params.get('status'))?.id,
    issue: params.get('issue') || undefined,
  }));
  const journalHref = workspaceHref();
  const request = isJournal ? undefined : requests.find(item => item.id === requestId);
  const title = isJournal ? 'Журнал запросов' : request?.title ?? 'Запрос';

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
    if (item.status === 'review' && item.issue?.label) {
      const label = item.issue.label;
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
  }, [preview, previewId]);

  function closePreview() {
    setPreviewId(undefined);
    previewTrigger.current?.focus();
  }

  function openPreview(id: string, trigger: HTMLButtonElement) {
    previewTrigger.current = trigger;
    setPreviewId(id);
  }

  return (
    <main className="stage stage--ascii stage--operator">
      <div className="workspace workspace--nav-mono">
        <nav className="rail rail--mono" aria-label="Навигация сотрудника">
          <span className="rail-emblem" aria-hidden="true"><AppIcon name="mark" size={20} /></span>
          <div className="rail-middle">
            <a className="rail-button" href={journalHref} title="Журнал запросов" aria-label="Журнал запросов" aria-current={isJournal ? 'page' : undefined}><AppIcon name="journal" size={20} /></a>
          </div>
          <div className="rail-utilities">
            <RailButton icon="test" title="Тест агента" onClick={() => setTesting(true)} />
          </div>
        </nav>

        <div className="desk">
          {isJournal ? (
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
                  <AnimatePresence initial={false}>
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
                <a className="screen-link" href={journalHref}><AppIcon name="back" size={17} />К журналу</a>
              </header>
              <div className="request-detail">
                {request ? <SelectedRequest request={request} /> : (
                  <div className="request-unavailable">
                    <h1>Запрос</h1>
                    {feedback}
                    {!loading && !error && <p>Запрос не найден в журнале.</p>}
                  </div>
                )}
              </div>
            </section>
          )}
        </div>
      </div>

      {testing && <AgentTestDialog onClose={() => setTesting(false)} />}
    </main>
  );
}
