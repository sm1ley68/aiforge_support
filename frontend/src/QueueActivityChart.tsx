import { useRef, useState, type CSSProperties } from 'react';
import { useInView } from 'motion/react';
import { AppIcon } from './AppIcon';
import { statuses } from './QueueAnalytics';
import type { QueueFilter } from './QueueControls';
import type { OperatorRequest, OperatorStatus } from './operator-types';

const hour = 3600_000;
const day = 24 * hour;
const timeZone = 'Europe/Moscow';
const clock = new Intl.DateTimeFormat('ru-RU', { timeZone, hour: '2-digit', minute: '2-digit' });
const calendar = new Intl.DateTimeFormat('ru-RU', { timeZone, day: 'numeric', month: 'short' });
const fullCalendar = new Intl.DateTimeFormat('ru-RU', { timeZone, day: 'numeric', month: 'long', year: 'numeric' });
const moscowDate = new Intl.DateTimeFormat('en-GB', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' });
const localTime = new Intl.DateTimeFormat('ru-RU', { timeZone, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
type Range = 'hourly' | 'daily';

function bucketTime(timestamp: number, range: Range) {
  if (range === 'hourly') return Math.floor(timestamp / hour) * hour;

  const [date, month, year] = moscowDate.format(timestamp).split('/');
  return Date.parse(`${year}-${month}-${date}T00:00:00Z`);
}

function activityBuckets(requests: OperatorRequest[], range: Range) {
  const countsByStart = new Map<number, Record<OperatorStatus, number>>();
  let latest = -Infinity;

  for (const request of requests) {
    const timestamp = Date.parse(request.updatedAt);
    if (!Number.isFinite(timestamp)) continue;
    const start = bucketTime(timestamp, range);
    latest = Math.max(latest, start);
    const counts = countsByStart.get(start) ?? { review: 0, waiting: 0, resolved: 0 };
    counts[request.status] += 1;
    countsByStart.set(start, counts);
  }

  if (!Number.isFinite(latest)) return [];
  const step = range === 'hourly' ? hour : day;
  const length = range === 'hourly' ? 6 : 7;

  return Array.from({ length }, (_, index) => {
    const start = latest - (length - 1 - index) * step;
    const counts = countsByStart.get(start) ?? { review: 0, waiting: 0, resolved: 0 };
    return { start, counts, total: counts.review + counts.waiting + counts.resolved };
  });
}

export function QueueActivityChart({ requests, journalHref }: {
  requests: OperatorRequest[];
  journalHref: (filter?: QueueFilter) => string;
}) {
  const [range, setRange] = useState<Range>('hourly');
  const [selectedBucket, setSelectedBucket] = useState<number>();
  const [tooltipDismissed, setTooltipDismissed] = useState(false);
  const frame = useRef<HTMLElement>(null);
  const inView = useInView(frame, { once: true });
  const buckets = activityBuckets(requests, range);
  const tickStep = Math.max(1, Math.ceil(Math.max(0, ...buckets.map(bucket => bucket.total)) / 4));
  const ticks = [4, 3, 2, 1, 0].map(tick => tick * tickStep);
  const last = buckets.at(-1);
  const spanLabel = last && (range === 'hourly'
    ? localTime.formatRange(buckets[0].start, last.start + hour - 60_000)
    : calendar.formatRange(buckets[0].start, last.start));

  function changeRange(next: Range) {
    if (next === range) return;
    setSelectedBucket(undefined);
    setTooltipDismissed(false);
    setRange(next);
  }

  return (
    <section
      ref={frame}
      className="dashboard-panel dashboard-activity"
      aria-labelledby="dashboard-activity-title"
      data-visible={inView || undefined}
      data-tooltip-dismissed={tooltipDismissed || undefined}
      onKeyDown={event => {
        if (event.key !== 'Escape') return;
        setTooltipDismissed(true);
        setSelectedBucket(undefined);
      }}
    >
      <header className="dashboard-section-heading dashboard-requests-heading">
        <div>
          <h2 id="dashboard-activity-title">Активность запросов</h2>
          {spanLabel && <p>{spanLabel} · МСК</p>}
        </div>
        <div className="dashboard-views" data-second={range === 'daily' || undefined} role="group" aria-label="Период графика">
          <button type="button" aria-pressed={range === 'hourly'} onClick={() => changeRange('hourly')}>6 часов</button>
          <button type="button" aria-pressed={range === 'daily'} onClick={() => changeRange('daily')}>7 дней</button>
        </div>
      </header>
      {buckets.length ? (
        <>
          <figure className="dashboard-activity-figure" aria-label="Количество запросов по времени их последнего обновления">
            <div className="dashboard-activity-plot">
              <div key={range} className="dashboard-activity-grid" aria-hidden="true">
                {ticks.map(tick => <div key={tick}><span>{tick}</span></div>)}
              </div>
              <div key={`bars-${range}`} className="dashboard-activity-bars">
                {buckets.map(({ start, counts, total }, index) => {
                  const label = range === 'hourly' ? localTime.format(start) : fullCalendar.format(start);
                  const breakdown = statuses.map(({ id, label }) => `${label.toLowerCase()}: ${counts[id]}`).join(', ');
                  if (!total) return <span key={start} className="dashboard-activity-bin" role="img" aria-label={`${label}. Нет запросов`} />;
                  return (
                    <button
                      key={start}
                      type="button"
                      className="dashboard-activity-bin"
                      aria-label={`${label}. Всего ${total}, ${breakdown}`}
                      aria-pressed={selectedBucket === start}
                      onPointerEnter={() => setTooltipDismissed(false)}
                      onFocus={() => setTooltipDismissed(false)}
                      onClick={() => {
                        setTooltipDismissed(false);
                        setSelectedBucket(current => current === start ? undefined : start);
                      }}
                      style={{ '--dashboard-bin-delay': `${index * 21}ms` } as CSSProperties}
                    >
                      <span className="dashboard-activity-stack" style={{ height: `${total / ticks[0] * 100}%` }} aria-hidden="true">
                        <span className="dashboard-activity-count">{total}</span>
                        <span className="dashboard-activity-fill">
                          {statuses.map(({ id }) => counts[id] > 0 && (
                            <span key={id} className="dashboard-activity-segment" data-tone={id} style={{ flexGrow: counts[id] }} />
                          ))}
                        </span>
                      </span>
                      <span className="dashboard-activity-tooltip" aria-hidden="true">
                        <strong>{label}</strong>
                        {statuses.map(({ id, label }) => <span key={id}>{label}<b>{counts[id]}</b></span>)}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
            <div key={range} className="dashboard-activity-labels" aria-hidden="true">
              {buckets.map(({ start }) => <span key={start}>{range === 'hourly' ? clock.format(start) : calendar.format(start).split(' ')[0]}</span>)}
            </div>
            <figcaption>По времени последнего обновления каждого запроса.</figcaption>
          </figure>
          <ul className="dashboard-activity-legend">
            {statuses.map(({ id, label }) => (
              <li key={id}>
                <a data-workspace-link href={journalHref({ status: id })} data-tone={id}>
                  <span className="dashboard-status-symbol" aria-hidden="true" />
                  {label}<AppIcon name="chevron" size={12} />
                </a>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="dashboard-empty">В журнале пока нет запросов с датой обновления.</p>}
    </section>
  );
}
