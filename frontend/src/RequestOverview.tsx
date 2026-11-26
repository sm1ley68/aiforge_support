import { useId, useState } from 'react';
import type { CSSProperties } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { AppIcon } from './AppIcon';
import type { IconName } from './AppIcon';
import { statuses } from './QueueAnalytics';
import type { OperatorRequest, RequestComparisonRow } from './operator-types';

type ComparisonState = RequestComparisonRow['state'];

const resultLabels = {
  match: 'Совпало',
  review: 'Уточнить',
  missing: 'Нет данных',
} satisfies Record<ComparisonState, string>;

const comparisonStates = ['match', 'review', 'missing'] as const;
const comparisonIcons = {
  match: 'comparisonMatch',
  review: 'comparisonReview',
  missing: 'comparisonMissing',
} satisfies Record<ComparisonState, IconName>;
const revealEase = [0.16, 1, 0.3, 1] as const;

function fallbackRows({ response, issue }: OperatorRequest): RequestComparisonRow[] {
  const rows: RequestComparisonRow[] = response.requirements.map(({ label, value }) => ({
    label, value, result: 'Нет сопоставления в ответе', state: 'missing',
  }));

  if (issue) {
    const checks = Array.isArray(issue.checks) ? issue.checks.filter(check => typeof check === 'string' && check.trim()) : [];
    for (const label of checks.length ? checks : [issue.label]) {
      rows.push({ label, result: 'Нужно проверить', state: 'review', detail: issue.detail });
    }
  }

  return rows;
}

export function RequestOverview({ request, onProducts }: {
  request: OperatorRequest;
  onProducts: () => void;
}) {
  const [filter, setFilter] = useState<ComparisonState | null>(null);
  const resultsId = useId();
  const reduceMotion = useReducedMotion();
  const { response, comparison } = request;
  const candidate = response.products.find(product => product.recommended);
  const comparisonRows = candidate && candidate.id === comparison?.productId && Array.isArray(comparison.rows)
    ? comparison.rows
    : [];
  const hasComparison = comparisonRows.length > 0;
  const rows = hasComparison ? comparisonRows : fallbackRows(request);
  const counts = { match: 0, review: 0, missing: 0 };
  for (const row of comparisonRows) counts[row.state] += 1;
  const activeFilter = filter && counts[filter] > 0 ? filter : null;
  const attentionCount = comparisonRows.length - counts.match;
  const waveHeight = hasComparison ? 44 * attentionCount / comparisonRows.length : 26;
  const tone = hasComparison ? (attentionCount ? 'review' : 'resolved') : request.status;
  const status = statuses.find(item => item.id === request.status);

  if (!rows.length && !response.products.length) return null;

  return (
    <section className="request-fit" aria-labelledby={`${resultsId}-title`}>
      <div className="request-fit-content">
        <header className="request-fit-header">
          <h3 id={`${resultsId}-title`}>Сопоставление условий</h3>
          {response.products.length > 0 && (
            <button type="button" className="request-fit-product" onClick={onProducts}>
              <AppIcon name="products" size={15} />
              <span>{candidate ? `${candidate.name}${candidate.version ? ` (${candidate.version})` : ''}` : 'Варианты подбора'}</span>
              <AppIcon name="chevron" size={15} />
            </button>
          )}
        </header>
        {hasComparison && (
          <div className="request-fit-breakdown">
            <div className="request-fit-track" aria-hidden="true">
              <motion.div
                className="request-fit-segments"
                initial={reduceMotion ? false : { scaleX: 0 }}
                animate={{ scaleX: 1 }}
                transition={{ duration: 0.48, delay: 0.04, ease: revealEase }}
              >
                {comparisonStates.map(state => counts[state] > 0 && (
                  <span key={state} data-state={state} data-muted={Boolean(activeFilter && activeFilter !== state)} style={{ flexGrow: counts[state] }} />
                ))}
              </motion.div>
            </div>
            <motion.div
              className="request-fit-filters"
              role="group"
              aria-label="Показать условия по результату"
              initial={reduceMotion ? false : { opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.14, ease: revealEase }}
            >
              {comparisonStates.map(state => (
                <button
                  key={state}
                  type="button"
                  data-state={state}
                  aria-pressed={activeFilter === state}
                  aria-controls={resultsId}
                  disabled={counts[state] === 0}
                  onClick={() => setFilter(activeFilter === state ? null : state)}
                >
                  <AppIcon name={comparisonIcons[state]} size={14} className="request-fit-legend-icon" />
                  <strong>{counts[state]}</strong> {resultLabels[state]}
                </button>
              ))}
            </motion.div>
          </div>
        )}
        {rows.length > 0 && (
          <ul className="request-fit-rows" id={resultsId} role="list">
            {rows.map((row, index) => {
              const source = row.sourceUrl ? response.sources.find(item => item.url === row.sourceUrl) : undefined;
              const hidden = Boolean(activeFilter && row.state !== activeFilter);
              const delay = (hasComparison ? 0.2 : 0.06) + Math.min(index, 5) * 0.042;
              return (
                <motion.li
                  className="request-fit-row"
                  key={`${row.label}-${index}`}
                  data-state={row.state}
                  hidden={hidden}
                  layout={reduceMotion || hidden ? false : 'position'}
                  initial={reduceMotion ? false : { opacity: 0, y: 11 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ default: { duration: 0.34, delay, ease: revealEase }, layout: { duration: 0.26, ease: revealEase } }}
                >
                  <details>
                    <summary className="request-fit-cell-row">
                      <motion.span
                        className="request-fit-state-icon"
                        title={resultLabels[row.state]}
                        initial={reduceMotion ? false : { scale: 0.72, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ scale: { type: 'spring', stiffness: 410, damping: 25, delay: delay + 0.065 }, opacity: { duration: 0.16, delay: delay + 0.065 } }}
                      >
                        <AppIcon name={comparisonIcons[row.state]} size={18} />
                        <span className="visually-hidden">{resultLabels[row.state]}</span>
                      </motion.span>
                      <span className="request-fit-condition"><small>{row.label}</small>{row.value && <strong>{row.value}</strong>}</span>
                    </summary>
                    <div className="request-fit-detail">
                      <strong>{row.result}</strong>
                      {row.detail && <p>{row.detail}</p>}
                      {source && <a href={source.url} target="_blank" rel="noreferrer"><AppIcon name="external" size={13} />{source.title}</a>}
                    </div>
                  </details>
                </motion.li>
              );
            })}
          </ul>
        )}
      </div>
      <div className="request-fit-status" data-status={tone} style={{ '--wave-height': `${waveHeight}%` } as CSSProperties}>
        <div className="request-fit-water" aria-hidden="true">
          <span className="request-fit-wave request-fit-wave--base" />
          <span className="request-fit-wave request-fit-wave--middle" />
          <span className="request-fit-wave request-fit-wave--edge" />
        </div>
        <div className="request-fit-status-copy">
          {hasComparison ? (
            <>
              <span>Требуют внимания</span>
              <p><strong>{attentionCount}</strong> из {comparisonRows.length}</p>
            </>
          ) : (
            <>
              <span>Статус запроса</span>
              <b><AppIcon name={request.status} size={17} />{status?.label}</b>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
