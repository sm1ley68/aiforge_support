import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { AgentTestDialog } from './AgentTestDialog';
import { AppIcon } from './AppIcon';
import type { IconName } from './AppIcon';
import { JournalTable, RequestPreview } from './JournalTable';
import { QueueAnalytics, statuses } from './QueueAnalytics';
import { RequestContext, RequestInspector, RequestTabContent } from './RequestInspector';
import { RequestOverview } from './RequestOverview';
import type { InspectorTab } from './RequestInspector';
import type { OperatorRequest, OperatorStatus } from './operator-types';
import { useOperatorQueue } from './use-operator-queue';

type QueueFilter = { status?: OperatorStatus; issue?: string };
type NavigationLayout = 'integrated' | 'compact' | 'left';

const detailTabs = [
  { id: 'dialog', label: 'Диалог', icon: 'journal' },
  { id: 'products', label: 'Подбор', icon: 'products' },
  { id: 'sources', label: 'Источники', icon: 'sources' },
] as const;
type DetailTab = typeof detailTabs[number]['id'];

const scenarioLabels = { known: 'Подбор редакции', discovery: 'Подбор по задаче', question: 'Вопрос о покупке' };
const journalTime = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' });
const journalDate = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' });
const ease = [0.22, 1, 0.36, 1] as const;

function formatTime(date: string, formatter = journalTime) {
  const time = Date.parse(date);
  return Number.isFinite(time) ? formatter.format(time) : '—';
}

function RailButton({ icon, title, active, label, count, onClick }: {
  icon: IconName;
  title: string;
  active?: boolean;
  label?: string;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button type="button" className={`rail-button${icon === 'test' ? ' rail-test' : ''}`} title={title} aria-label={title} aria-pressed={active} onClick={onClick}>
      {active && <motion.span className="rail-active" layoutId="rail-active" transition={{ type: 'spring', stiffness: 360, damping: 33 }} />}
      <AppIcon name={icon} size={label ? 19 : 23} />
      {label && <span>{label}</span>}
      {count !== undefined && <b className="rail-count">{count}</b>}
    </button>
  );
}

function RequestRow({ request, active, onClick }: { request: OperatorRequest; active: boolean; onClick: () => void }) {
  const status = statuses.find(item => item.id === request.status);
  return (
    <button type="button" className={`request-row${active ? ' request-row--active' : ''}`} aria-pressed={active} onClick={onClick}>
      <span className={`request-icon status-fill--${request.status}`} aria-hidden="true"><AppIcon name={request.status} size={18} /></span>
      <span className="request-main"><strong>{request.title}</strong><span>{request.customer}</span></span>
      <span className="request-meta">
        <time dateTime={request.updatedAt} title={formatTime(request.updatedAt, journalDate)}>{formatTime(request.updatedAt)}</time>
        <span className={`request-status request-status--${request.status}`}>{status?.short}</span>
      </span>
    </button>
  );
}

function RequestHeading({ request, showStatus = false }: { request: OperatorRequest; showStatus?: boolean }) {
  const status = statuses.find(item => item.id === request.status);
  const Heading = showStatus ? 'h1' : 'h2';

  return (
    <header className="thread-heading">
      <div className="thread-scenario">
        {showStatus && <b className={`request-status request-status--${request.status}`}>{status?.label}</b>}
        {scenarioLabels[request.scenario]}
        <span>#{request.id}</span>
      </div>
      <Heading>{request.title}</Heading>
      <p>{request.customer} <span>·</span> <time dateTime={request.updatedAt}>{formatTime(request.updatedAt, journalDate)} МСК</time></p>
    </header>
  );
}

function RequestMessages({ request }: { request: OperatorRequest }) {
  return (
    <div className="thread-messages" aria-label="Сообщения">
      {request.response.messages.length ? (
        request.response.messages.map((message, index) => (
          <article className={`thread-message thread-message--${message.role}`} key={index}>
            <span className="thread-message-icon" aria-hidden="true">
              <AppIcon name={message.role === 'assistant' ? 'agent' : 'client'} size={16} />
            </span>
            <div><h3>{message.role === 'assistant' ? 'Агент Store' : 'Клиент'}</h3><p>{message.content}</p></div>
          </article>
        ))
      ) : <p className="journal-empty">Сообщений в запросе пока нет.</p>}
    </div>
  );
}

function RequestThread({ request, revealInspector }: { request?: OperatorRequest; revealInspector: (tab: InspectorTab) => void }) {
  return (
    <section className="thread" aria-label="Диалог по выбранному запросу">
      <AnimatePresence initial={false} mode="popLayout">
        {request ? (
          <motion.div
            className="thread-view"
            key={request.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, transition: { duration: 0.12 } }}
            transition={{ duration: 0.26, ease }}
          >
            <RequestHeading request={request} />
            <RequestMessages request={request} />
            <div className="thread-footer">
              <button type="button" onClick={() => revealInspector('products')}><AppIcon name="products" size={15} /> Подбор <b>{request.response.products.length}</b></button>
              <button type="button" onClick={() => revealInspector('sources')}><AppIcon name="sources" size={15} /> Источники <b>{request.response.sources.length}</b></button>
            </div>
          </motion.div>
        ) : (
          <motion.div className="thread-empty" key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <AppIcon name="journal" size={28} /><p>Выберите запрос, чтобы открыть диалог.</p>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function SelectedRequest({ request }: { request: OperatorRequest }) {
  const [tab, setTab] = useState<DetailTab>('dialog');
  const tabGroup = useRef<HTMLDivElement>(null);
  const { response } = request;

  function openProducts() {
    setTab('products');
    tabGroup.current?.querySelector<HTMLButtonElement>('[data-tab="products"]')?.focus();
  }

  return (
    <>
      <RequestHeading request={request} showStatus />
      <div ref={tabGroup} className="detail-tabs" role="group" aria-label="Материалы запроса">
        {detailTabs.map(item => (
          <button type="button" key={item.id} data-tab={item.id} aria-pressed={tab === item.id} onClick={() => setTab(item.id)}>
            <AppIcon name={item.icon} size={15} />
            {item.label}
            {(item.id === 'products' || item.id === 'sources') && <span>{response[item.id].length}</span>}
          </button>
        ))}
      </div>
      {tab === 'dialog' ? (
        <div className="request-dialog-view">
          <RequestOverview request={request} onProducts={openProducts} />
          <div className={`request-conversation${response.trace.length ? ' request-conversation--with-trace' : ''}`}>
            <RequestMessages request={request} />
            {response.trace.length > 0 && (
              <aside className="detail-context" aria-label="Ход работы агента">
                <RequestContext response={response} showConditions={false} />
              </aside>
            )}
          </div>
        </div>
      ) : (
        <div className="detail-tab-content">
          <RequestTabContent key={tab} response={response} tab={tab} />
        </div>
      )}
    </>
  );
}

function filterRequests(requests: OperatorRequest[], filter: QueueFilter, query: string) {
  const needle = query.trim().toLocaleLowerCase('ru-RU');

  return requests.filter(request =>
    (!filter.status || request.status === filter.status) &&
    (!filter.issue || request.issue?.label === filter.issue) &&
    (!needle || [request.id, request.title, request.customer, request.issue?.label ?? '', request.issue?.detail ?? '',
      ...request.response.messages.map(message => message.content)]
      .some(value => value.toLocaleLowerCase('ru-RU').includes(needle))),
  ).sort((first, second) => Date.parse(second.updatedAt) - Date.parse(first.updatedAt));
}

function QueueSearch({ query, onQuery }: { query: string; onQuery: (value: string) => void }) {
  return (
    <label className="queue-search">
      <AppIcon name="search" size={17} />
      <input aria-label="Поиск по журналу" type="search" value={query} onChange={event => onQuery(event.currentTarget.value)} placeholder="Поиск по журналу" />
    </label>
  );
}

function QueueFeedback({ loading, error, reload }: { loading: boolean; error: string; reload: () => void }) {
  if (error) return <p className="journal-empty" role="alert">{error} <button type="button" onClick={reload}>Повторить</button></p>;
  if (loading) return <p className="journal-empty" role="status">Загрузка запросов…</p>;
  return null;
}

function workspaceHref(route: Record<string, string> = {}) {
  const url = new URL(window.location.href);
  for (const key of ['view', 'status', 'issue', 'request']) url.searchParams.delete(key);
  for (const [key, value] of Object.entries(route)) url.searchParams.set(key, value);
  return url.pathname + url.search;
}

function Workspace() {
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

function NavigationDemo({ navigation }: { navigation: NavigationLayout }) {
  const { requests, loading, error, reload } = useOperatorQueue();
  const [filter, setFilter] = useState<QueueFilter>({});
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string>();
  const [tab, setTab] = useState<InspectorTab>('actions');
  const [testing, setTesting] = useState(false);
  const allRequests = !filter.status && !filter.issue;
  const filtered = filterRequests(requests, filter, query);
  const selected = filtered.find(request => request.id === selectedId) ?? filtered[0];

  function reveal(section: string) {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const element = document.getElementById(section);
    element?.focus({ preventScroll: true });
    element?.scrollIntoView({ block: 'nearest', behavior: reduce ? 'instant' : 'smooth' });
  }

  function revealQueue(nextFilter: QueueFilter) {
    setFilter(nextFilter);
    setQuery('');
    requestAnimationFrame(() => reveal('journal'));
  }

  function revealInspector(nextTab: InspectorTab) {
    setTab(nextTab);
    reveal('inspector');
  }

  const labeledNavigation = navigation === 'left';
  const navigationRail = (
    <nav className={`rail rail--${navigation}`} aria-label="Навигация сотрудника">
      <div className="rail-middle">
        <RailButton icon="journal" title="Журнал запросов" label={labeledNavigation ? 'Журнал' : undefined} active={allRequests} onClick={() => revealQueue({})} />
        <RailButton icon="review" title="Запросы на проверку" label={labeledNavigation ? 'На проверку' : undefined} count={labeledNavigation ? requests.filter(request => request.status === 'review').length : undefined} active={filter.status === 'review'} onClick={() => revealQueue({ status: 'review' })} />
      </div>
      <RailButton icon="test" title="Тест агента" label={labeledNavigation ? 'Тест агента' : undefined} onClick={() => setTesting(true)} />
    </nav>
  );

  return (
    <main className="stage">
      <motion.div className={`workspace workspace--nav-${navigation}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease }}>
        {navigation === 'left' && navigationRail}
        <div className="desk">
          <section id="journal" tabIndex={-1} className="journal" aria-labelledby="journal-title">
            <header className="app-header">
              <div className="brand"><span className="brand-icon" aria-hidden="true"><AppIcon name="mark" size={21} /></span><span>Softline <b>Store</b></span></div>
              <div className="queue-tabs" role="group" aria-label="Статус запроса">
                <button type="button" aria-pressed={allRequests} onClick={() => setFilter({})}>
                  {allRequests && <motion.span className="queue-tab-active" layoutId="queue-tab" />}Все
                </button>
                {statuses.map(status => (
                  <button type="button" aria-pressed={filter.status === status.id} key={status.id} onClick={() => setFilter({ status: status.id })}>
                    {filter.status === status.id && <motion.span className="queue-tab-active" layoutId="queue-tab" />}{status.label}
                  </button>
                ))}
              </div>
            </header>
            <div className="journal-heading">
              <div><p>Рабочее место сотрудника</p><h1 id="journal-title">Журнал запросов</h1></div>
              <QueueSearch query={query} onQuery={setQuery} />
            </div>
            <div className="journal-body">
              <section className="queue" aria-label="Список запросов" aria-busy={loading}>
                <div className="queue-heading">
                  <strong>{loading ? 'Загрузка' : `Запросов: ${filtered.length}`}</strong>
                  {filter.issue ? (
                    <button type="button" className="issue-filter" onClick={() => setFilter({})} aria-label={`Снять фильтр «${filter.issue}»`}>
                      <span>{filter.issue}</span><AppIcon name="close" size={13} />
                    </button>
                  ) : <span>Обновление</span>}
                </div>
                <div className="request-list">
                  <QueueFeedback loading={loading} error={error} reload={reload} />
                  {filtered.map(request => (
                    <RequestRow key={request.id} request={request} active={request.id === selected?.id} onClick={() => setSelectedId(request.id)} />
                  ))}
                  {!filtered.length && !loading && !error && <p className="journal-empty">{query.trim() || !allRequests ? 'По этому фильтру ничего не найдено.' : 'Журнал пока пуст.'}</p>}
                </div>
              </section>
              <RequestThread request={selected} revealInspector={revealInspector} />
            </div>
          </section>

          <QueueAnalytics requests={requests} visibleRequests={filtered} onStatus={status => revealQueue({ status })} onIssue={issue => revealQueue({ issue })} />
        </div>

        <RequestInspector request={selected} tab={tab} onTab={setTab} onTest={navigation === 'integrated' ? () => setTesting(true) : undefined} />
        {navigation === 'compact' && navigationRail}
      </motion.div>

      {testing && <AgentTestDialog onClose={() => setTesting(false)} />}
    </main>
  );
}

export function App({ navigation }: { navigation?: NavigationLayout }) {
  return navigation ? <NavigationDemo navigation={navigation} /> : <Workspace />;
}
