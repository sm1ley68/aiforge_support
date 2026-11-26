import { useState } from 'react';
import { motion } from 'motion/react';
import { AgentTestDialog } from './AgentTestDialog';
import { AppIcon } from './AppIcon';
import { QueueAnalytics, statuses } from './QueueAnalytics';
import { QueueFeedback, QueueSearch, filterRequests } from './QueueControls';
import type { QueueFilter } from './QueueControls';
import { RailButton } from './RailButton';
import { RequestInspector } from './RequestInspector';
import type { InspectorTab } from './RequestInspector';
import { RequestRow, RequestThread } from './RequestViews';
import { useOperatorQueue } from './use-operator-queue';

export type NavigationLayout = 'integrated' | 'compact' | 'left';

const ease = [0.22, 1, 0.36, 1] as const;

export function NavigationDemo({ navigation }: { navigation: NavigationLayout }) {
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
