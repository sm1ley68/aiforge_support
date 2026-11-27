import { useId, useState } from 'react';
import type { CSSProperties } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { AppIcon } from './AppIcon';
import type { IconName } from './AppIcon';
import type { Source } from './agent-types';
import { statuses } from './QueueAnalytics';
import type { OperatorRequest, RequestComparisonRow } from './operator-types';

type ComparisonState = RequestComparisonRow['state'];

type ComparisonCounts = Record<ComparisonState, number>;

const comparisonStates = ['match', 'review', 'missing'] as const;
const comparisonResults = {
  match: { label: 'Совпало', icon: 'comparisonMatch' },
  review: { label: 'Уточнить', icon: 'comparisonReview' },
  missing: { label: 'Нет данных', icon: 'comparisonMissing' },
} satisfies Record<ComparisonState, { label: string; icon: IconName }>;
const revealEase = [0.16, 1, 0.3, 1] as const;

function fallbackRows({ response, issue }: OperatorRequest, showReason = true): RequestComparisonRow[] {
  const rows: RequestComparisonRow[] = response.requirements.map(({ label, value }) => ({
    label, value, result: 'Нет сопоставления в ответе', state: 'missing',
  }));

  if (issue) {
    const checks = Array.isArray(issue.checks) ? issue.checks.filter(check => typeof check === 'string' && check.trim()) : [];
    for (const label of checks.length ? checks : showReason ? [issue.label] : []) {
      rows.push({ label, result: 'Нужно проверить', state: 'review', detail: issue.detail });
    }
  }

  return rows;
}

function ComparisonBreakdown({ counts, activeFilter, resultsId, onFilter, reduceMotion }: {
  counts: ComparisonCounts;
  activeFilter: ComparisonState | null;
  resultsId: string;
  onFilter: (filter: ComparisonState | null) => void;
  reduceMotion: boolean;
}) {
  return (
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
            onClick={() => onFilter(activeFilter === state ? null : state)}
          >
            <AppIcon name={comparisonResults[state].icon} size={14} className="request-fit-legend-icon" />
            <strong>{counts[state]}</strong> {comparisonResults[state].label}
          </button>
        ))}
      </motion.div>
    </div>
  );
}

function ComparisonResult({ row, source, hidden, delay, reduceMotion }: {
  row: RequestComparisonRow;
  source?: Source;
  hidden: boolean;
  delay: number;
  reduceMotion: boolean;
}) {
  const result = comparisonResults[row.state];

  return (
    <motion.li
      className="request-fit-row"
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
            title={result?.label}
            initial={reduceMotion ? false : { scale: 0.72, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ scale: { type: 'spring', stiffness: 410, damping: 25, delay: delay + 0.065 }, opacity: { duration: 0.16, delay: delay + 0.065 } }}
          >
            <AppIcon name={result?.icon} size={18} />
            <span className="visually-hidden">{result?.label}</span>
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
}

export function RequestOverview({ request, onProducts, live = false }: {
  request: OperatorRequest;
  onProducts: () => void;
  live?: boolean;
}) {
  const [filter, setFilter] = useState<ComparisonState | null>(null);
  const resultsId = useId();
  const reduceMotion = useReducedMotion() ?? false;
  const { response, comparison } = request;
  const candidate = response.products.find(product => product.recommended);
  const comparisonRows = candidate && candidate.id === comparison?.productId && Array.isArray(comparison.rows)
    ? comparison.rows
    : [];
  const hasComparison = comparisonRows.length > 0;
  const reason = live ? request.issue : undefined;
  const rows = hasComparison ? comparisonRows : fallbackRows(request, !reason);
  const product = candidate ?? (live && response.products.length === 1 ? response.products[0] : undefined);
  const counts: ComparisonCounts = { match: 0, review: 0, missing: 0 };
  for (const row of comparisonRows) counts[row.state] += 1;
  const activeFilter = filter && counts[filter] > 0 ? filter : null;
  const attentionCount = comparisonRows.length - counts.match;
  const showCaseStatus = live || !hasComparison;
  const waveHeight = showCaseStatus ? 26 : 44 * attentionCount / comparisonRows.length;
  const tone = showCaseStatus ? request.status : attentionCount ? 'review' : 'resolved';
  const status = statuses.find(item => item.id === request.status);
  const reasonOnly = Boolean(reason && !rows.length && response.products.length === 0);

  if (!rows.length && !response.products.length && !reason) return null;

  return (
    <section className={live ? 'request-fit request-fit--live' : 'request-fit'} aria-labelledby={`${resultsId}-title`}>
      <div className="request-fit-content">
        <header className="request-fit-header">
          <h3 id={`${resultsId}-title`}>{reasonOnly ? 'Причина передачи' : 'Сопоставление условий'}</h3>
          {response.products.length > 0 && (
            <button type="button" className="request-fit-product" onClick={onProducts}>
              <AppIcon name="products" size={15} />
              <span>{product ? `${product.name}${product.version ? ` (${product.version})` : ''}` : 'Варианты подбора'}</span>
              <AppIcon name="chevron" size={15} />
            </button>
          )}
        </header>
        {reason && <div className="request-fit-reason" role={reasonOnly ? undefined : 'region'} aria-label={reasonOnly ? undefined : 'Причина передачи'}>
          {!reasonOnly && <span>Причина передачи</span>}
          <strong>{reason.label}</strong>
          {reason.detail !== reason.label && <p>{reason.detail}</p>}
        </div>}
        {hasComparison && (
          <ComparisonBreakdown
            counts={counts}
            activeFilter={activeFilter}
            resultsId={resultsId}
            onFilter={setFilter}
            reduceMotion={reduceMotion}
          />
        )}
        {rows.length > 0 && (
          <ul className="request-fit-rows" id={resultsId} role="list">
            {rows.map((row, index) => {
              const source = row.sourceUrl ? response.sources.find(item => item.url === row.sourceUrl) : undefined;
              const hidden = Boolean(activeFilter && row.state !== activeFilter);
              const delay = (hasComparison ? 0.2 : 0.06) + Math.min(index, 5) * 0.042;
              return (
                <ComparisonResult
                  key={`${row.label}-${index}`}
                  row={row}
                  source={source}
                  hidden={hidden}
                  delay={delay}
                  reduceMotion={reduceMotion}
                />
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
          {showCaseStatus ? (
            <>
              <span>Статус запроса</span>
              <b><AppIcon name={request.status} size={17} />{live && request.status === 'review' ? 'Требуется действие' : status?.label}</b>
            </>
          ) : (
            <>
              <span>Требуют внимания</span>
              <p><strong>{attentionCount}</strong> из {comparisonRows.length}</p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
