import { AppIcon } from './AppIcon';
import type { OperatorRequest, OperatorStatus } from './operator-types';

export type QueueFilter = { status?: OperatorStatus; issue?: string };

export function filterRequests(requests: OperatorRequest[], filter: QueueFilter, query: string) {
  const needle = query.trim().toLocaleLowerCase('ru-RU');

  return requests.filter(request =>
    (!filter.status || request.status === filter.status) &&
    (!filter.issue || request.issue?.label === filter.issue) &&
    (!needle || [request.id, request.title, request.customer, request.issue?.label ?? '', request.issue?.detail ?? '',
      ...request.response.messages.map(message => message.content)]
      .some(value => value.toLocaleLowerCase('ru-RU').includes(needle))),
  ).sort((first, second) => Date.parse(second.updatedAt) - Date.parse(first.updatedAt));
}

export function QueueSearch({ query, onQuery }: { query: string; onQuery: (value: string) => void }) {
  return (
    <label className="queue-search">
      <AppIcon name="search" size={17} />
      <input aria-label="Поиск по журналу" type="search" value={query} onChange={event => onQuery(event.currentTarget.value)} placeholder="Поиск по журналу" />
    </label>
  );
}

export function QueueFeedback({ loading, error, reload }: { loading: boolean; error: string; reload: () => void }) {
  if (error) return <p className="journal-empty" role="alert">{error} <button type="button" onClick={reload}>Повторить</button></p>;
  if (loading) return <p className="journal-empty" role="status">Загрузка запросов…</p>;
  return null;
}
