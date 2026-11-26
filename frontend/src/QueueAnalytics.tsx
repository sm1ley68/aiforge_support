import { AppIcon } from './AppIcon';
import { motion, useTransform } from 'motion/react';
import type { MotionValue } from 'motion/react';
import { useState } from 'react';
import type { CSSProperties } from 'react';
import type { OperatorRequest, OperatorStatus } from './operator-types';
import { usePointerDepth } from './use-pointer-depth';

export const statuses: { id: OperatorStatus; label: string; short: string }[] = [
  { id: 'review', label: 'На проверку', short: 'Проверка' },
  { id: 'waiting', label: 'Ждут клиента', short: 'Ожидание' },
  { id: 'resolved', label: 'Завершены', short: 'Готово' },
];

const gaugeStatuses = [...statuses].reverse();
const bubbleDepth = { recommended: 8, links: 13, empty: 19 };

function OutcomeBubble({ id, share, pointer }: {
  id: keyof typeof bubbleDepth;
  share: number;
  pointer: { x: MotionValue<number>; y: MotionValue<number> };
}) {
  const distance = bubbleDepth[id];
  const x = useTransform(pointer.x, value => value * distance);
  const y = useTransform(pointer.y, value => value * distance * 0.7);

  return (
    <motion.div className={`outcome-bubble outcome-bubble--${id}`} style={{ x, y }}>
      <span>{share}<small>%</small></span>
    </motion.div>
  );
}

export function QueueAnalytics({ requests, visibleRequests, onStatus, onIssue, activeStatus, activeIssue }: {
  requests: OperatorRequest[];
  visibleRequests?: OperatorRequest[];
  onStatus: (status: OperatorStatus) => void;
  onIssue: (issue: string) => void;
  activeStatus?: OperatorStatus;
  activeIssue?: string;
}) {
  const inJournal = visibleRequests === undefined;
  const [visibleOnly, setVisibleOnly] = useState(false);
  const gaugePointer = usePointerDepth();
  const bubblePointer = usePointerDepth();
  const gaugeX = useTransform(gaugePointer.x, value => value * 4);
  const gaugeY = useTransform(gaugePointer.y, value => value * 3);
  const gaugeLabelX = useTransform(gaugePointer.x, value => value * 8);
  const gaugeLabelY = useTransform(gaugePointer.y, value => value * 5);
  const scope = visibleOnly && visibleRequests ? visibleRequests : requests;
  const counts = { review: 0, waiting: 0, resolved: 0 };
  const issueCounts = new Map<string, number>();
  let recommended = 0;
  let sourced = 0;
  let linksOnly = 0;

  for (const request of scope) {
    const hasRecommendation = request.response.products.some(product => product.recommended);
    const hasSources = request.response.sources.length > 0;
    counts[request.status] += 1;
    if (hasRecommendation) recommended += 1;
    if (hasSources) sourced += 1;
    if (hasSources && !hasRecommendation) linksOnly += 1;
    if (request.issue?.label && (!inJournal || request.status === 'review')) {
      const { label } = request.issue;
      issueCounts.set(label, (issueCounts.get(label) ?? 0) + 1);
    }
  }

  const issues = [...issueCounts].sort((first, second) => second[1] - first[1]);
  const reviewsWithoutReason = counts.review - issues.reduce((total, [, count]) => total + count, 0);
  const share = (count: number) => scope.length ? Math.round(count / scope.length * 100) : 0;
  const angle = (count: number) => scope.length ? `${count / scope.length * 180}deg` : '0deg';
  const outcomes = [
    { id: 'recommended', label: 'С рекомендацией', count: recommended },
    { id: 'links', label: 'Только источники', count: linksOnly },
    { id: 'empty', label: 'Без рекомендации и источников', count: scope.length - recommended - linksOnly },
  ] as const;

  return (
    <section
      className={inJournal ? 'analytics analytics--journal' : 'analytics'}
      id="analytics"
      aria-label={inJournal ? 'Состояние очереди и результаты агента' : undefined}
      aria-labelledby={inJournal ? undefined : 'analytics-title'}
      tabIndex={-1}
    >
      {!inJournal && (
        <header className="analytics-toolbar">
          <h2 id="analytics-title"><AppIcon name="chart" size={16} /> Сводка журнала</h2>
          <div className="analytics-scope" role="group" aria-label="Какие запросы учитывать в сводке">
            <button type="button" aria-pressed={!visibleOnly} onClick={() => setVisibleOnly(false)}>Весь журнал</button>
            <button type="button" aria-pressed={visibleOnly} onClick={() => setVisibleOnly(true)}>По фильтру</button>
          </div>
        </header>
      )}

      <div className="analytics-grid">
        <section className="metric metric--queue" {...gaugePointer.handlers}>
          <h3>Состояние очереди</h3>
          <div className="metric-plot gauge-plot" style={{ '--resolved-angle': angle(counts.resolved), '--review-angle': angle(counts.review) } as CSSProperties}>
            <motion.div className="queue-gauge" style={{ x: gaugeX, y: gaugeY }}>
              <span className="gauge-arc gauge-arc--resolved" aria-hidden="true" />
              <span className="gauge-arc gauge-arc--review" aria-hidden="true" />
              <motion.span className="gauge-total" style={{ x: gaugeLabelX, y: gaugeLabelY }}>
                {inJournal ? <><b>{scope.length}</b> всего</> : <><AppIcon name="journal" size={13} /> Запросов: <b>{scope.length}</b></>}
              </motion.span>
            </motion.div>
          </div>
          <div className="gauge-legend">
            {(inJournal ? statuses : gaugeStatuses).map(status => (
              <button type="button" key={status.id} data-status={status.id} onClick={() => onStatus(status.id)} aria-pressed={inJournal ? activeStatus === status.id : undefined} aria-label={`${status.label}: ${counts[status.id]} из ${scope.length}, ${share(counts[status.id])}%`}>
                <strong>{inJournal ? counts[status.id] : <>{share(counts[status.id])}<small>%</small></>}</strong>
                <span><i className={`status-fill--${status.id}`} />{inJournal ? status.label : status.short}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="metric metric--results" {...bubblePointer.handlers}>
          <header className="metric-heading">
            <h3>Результат агента</h3>
            <span>С источниками: <b>{sourced}{inJournal && ` из ${scope.length}`}</b></span>
          </header>
          <div className="metric-plot bubble-plot" aria-hidden="true">
            {outcomes.map(outcome => (
              <OutcomeBubble key={outcome.id} id={outcome.id} share={share(outcome.count)} pointer={bubblePointer} />
            ))}
          </div>
          <dl className="bubble-legend">
            {outcomes.map(outcome => (
              <div key={outcome.id} className={`bubble-legend--${outcome.id}`}>
                <dt>{outcome.label}</dt><dd>{outcome.count}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="metric metric--issues">
          <h3>{inJournal ? 'Причины ручной проверки' : 'Требуют внимания'}</h3>
          {issues.length ? (
            <ul className="issue-columns">
              {issues.map(([label, count], index) => (
                <li key={label}>
                  <button
                    type="button"
                    className={`issue-column issue-column--${index % 3}`}
                    style={{ '--bar': `${count / issues[0][1] * 100}%` } as CSSProperties}
                    title={label}
                    aria-label={`${label}: ${count}. Показать запросы`}
                    aria-pressed={inJournal ? activeIssue === label : undefined}
                    onClick={() => onIssue(label)}
                  >
                    <span className="issue-column-plot" aria-hidden="true">
                      <span className="issue-column-bar"><span className="issue-column-value">{count}<AppIcon name="filter" size={11} /></span></span>
                    </span>
                    <span className="issue-column-label">{label}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="metric-empty">{inJournal ? counts.review ? 'Причины не указаны.' : 'Запросов на проверку нет.' : 'Нет отмеченных проблем.'}</p>}
          {inJournal && issues.length > 0 && reviewsWithoutReason > 0 && <p className="metric-empty">Без указанной причины: {reviewsWithoutReason}</p>}
        </section>
      </div>
    </section>
  );
}
