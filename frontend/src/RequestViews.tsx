import { useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { AppIcon } from './AppIcon';
import { statuses } from './QueueAnalytics';
import { LiveManagerCase } from './LiveManagerCase';
import { RequestContext, RequestTabContent } from './RequestInspector';
import type { InspectorTab } from './RequestInspector';
import { RequestMessages } from './RequestMessages';
import { RequestOverview } from './RequestOverview';
import type { OperatorRequest } from './operator-types';

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

export function RequestRow({ request, active, onClick }: { request: OperatorRequest; active: boolean; onClick: () => void }) {
  const status = statuses.find(item => item.id === request.status);
  return (
    <button type="button" className={`request-row${active ? ' request-row--active' : ''}`} aria-pressed={active} onClick={onClick}>
      <span className={`request-icon status-fill--${request.status}`} aria-hidden="true"><AppIcon name={request.status} size={18} /></span>
      <span className="request-main"><strong>{request.title}</strong><span>{request.customer}</span></span>
      <span className="request-meta">
        <time dateTime={request.updatedAt} title={formatTime(request.updatedAt, journalDate)}>{formatTime(request.updatedAt)}</time>
        <span className={`request-status request-status--${request.status}`}>{request.needsReply ? 'Ответить' : status?.short}</span>
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
        {showStatus && <b className={`request-status request-status--${request.status}`}>{request.needsReply ? 'Ответить' : status?.label}</b>}
        {scenarioLabels[request.scenario]}
        <span>#{request.id}</span>
      </div>
      <Heading>{request.title}</Heading>
      <p>{request.customer} <span>·</span> <time dateTime={request.updatedAt}>{formatTime(request.updatedAt, journalDate)} МСК</time></p>
    </header>
  );
}

export function RequestThread({ request, revealInspector }: { request?: OperatorRequest; revealInspector: (tab: InspectorTab) => void }) {
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
            <RequestMessages messages={request.response.messages} />
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

export function SelectedRequest({ request, reviewQueue, requestHref, reload }: {
  request: OperatorRequest;
  reviewQueue: OperatorRequest[];
  requestHref: (id: string) => string;
  reload: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>('dialog');
  const [startingOrder] = useState(() => reviewQueue.map(item => item.id));
  const tabGroup = useRef<HTMLDivElement>(null);
  const { response } = request;
  const showTrace = response.trace.length > 0;
  const available = new Set(reviewQueue.map(item => item.id));
  available.delete(request.id);
  const nextId = startingOrder.slice(startingOrder.indexOf(request.id) + 1).find(id => available.has(id))
    ?? reviewQueue.find(item => item.id !== request.id)?.id;

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
        <div className="request-dialog-view operator-detail-tab" key="dialog">
          <RequestOverview request={request} onProducts={openProducts} live />
          <div className={`request-conversation${showTrace ? ' request-conversation--with-trace' : ''}`}>
            <LiveManagerCase request={request} nextHref={nextId && requestHref(nextId)} reload={reload} />
            {showTrace && (
              <aside className="detail-context" aria-label="Ход работы агента">
                <RequestContext response={response} showConditions={false} />
              </aside>
            )}
          </div>
        </div>
      ) : (
        <div className="detail-tab-content operator-detail-tab" key={tab}>
          <RequestTabContent key={tab} response={response} tab={tab} />
        </div>
      )}
    </>
  );
}
