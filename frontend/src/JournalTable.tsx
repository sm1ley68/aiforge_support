import { AppIcon } from './AppIcon';
import { reviewReason } from './QueueControls';
import { RequestStatus, requestPreviewId } from './RequestPreview';
import type { OperatorRequest } from './operator-types';

const timeZone = 'Europe/Moscow';
const clock = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone });
const calendar = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone });

export function JournalTable({ requests, selectedId, onOpen }: {
  requests: OperatorRequest[];
  selectedId?: string;
  onOpen: (id: string, trigger: HTMLButtonElement) => void;
}) {
  return (
    <table className="operator-table" aria-label="Список запросов" role="table">
      <thead role="rowgroup">
        <tr role="row">
          <th role="columnheader" scope="col">Запрос / компания</th>
          <th role="columnheader" scope="col">Причина проверки</th>
          <th role="columnheader" scope="col">Статус</th>
          <th role="columnheader" scope="col" aria-sort="descending">Обновлён</th>
        </tr>
      </thead>
      <tbody role="rowgroup">
        {requests.map(request => {
          const timestamp = Date.parse(request.updatedAt);
          const hasDate = Number.isFinite(timestamp);
          const reason = request.status === 'review' ? reviewReason(request) : undefined;
          const selected = request.id === selectedId;
          return (
            <tr key={request.id} role="row" data-current={selected || undefined}>
              <td className="operator-title" role="cell">
                <button
                  type="button"
                  aria-expanded={selected}
                  aria-controls={selectedId ? requestPreviewId : undefined}
                  onClick={event => onOpen(request.id, event.currentTarget)}
                >
                  {request.title}
                </button>
                <span>{request.customer}</span>
              </td>
              <td className="operator-reason" role="cell" data-empty={reason ? undefined : true}>{reason ?? '—'}</td>
              <td className="operator-row-status" role="cell"><RequestStatus status={request.status} needsReply={request.needsReply} /></td>
              <td className="operator-time" role="cell">
                {hasDate ? <time dateTime={request.updatedAt} title="Московское время">{clock.format(timestamp)}<small>{calendar.format(timestamp)}</small></time> : '—'}
                <AppIcon name="chevron" className="operator-row-arrow" size={16} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
