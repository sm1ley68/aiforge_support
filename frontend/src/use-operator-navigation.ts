import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react';
import { statuses } from './QueueAnalytics';
import type { QueueFilter } from './QueueControls';

const historyKey = 'softlineOperatorEntry';
let visitSequence = 0;

function newEntryId() {
  return `${performance.timeOrigin}-${visitSequence++}`;
}

function entryIdFrom(state: unknown) {
  if (state && typeof state === 'object' && historyKey in state && typeof state[historyKey] === 'string') {
    return state[historyKey];
  }
}

function filterFrom(search: string): QueueFilter {
  const params = new URLSearchParams(search);
  return {
    status: statuses.find(status => status.id === params.get('status'))?.id,
    issue: params.get('issue') || undefined,
  };
}

export function workspaceHref(route: Record<string, string> = {}) {
  const url = new URL(window.location.href);
  for (const key of ['view', 'status', 'issue', 'request']) url.searchParams.delete(key);
  for (const [key, value] of Object.entries(route)) url.searchParams.set(key, value);
  return url.pathname + url.search;
}

export function journalHref({ status, issue }: QueueFilter = {}) {
  return workspaceHref({ view: 'journal', ...(status && { status }), ...(issue && { issue }) });
}

type Visit = {
  filter: QueueFilter;
  query: string;
  previewId?: string;
  scrollTop: number;
};

export function useOperatorNavigation() {
  const [route, setRoute] = useState(() => ({
    entryId: entryIdFrom(window.history.state) ?? newEntryId(),
    search: window.location.search,
    scrollTop: 0,
    moved: false,
  }));
  const [filter, setFilter] = useState(() => filterFrom(route.search));
  const [query, setQuery] = useState('');
  const [previewId, setPreviewId] = useState<string>();
  const desk = useRef<HTMLDivElement>(null);
  const visits = useRef(new Map<string, Visit>());
  const requestsOpenedFromJournal = useRef(new Set<string>());
  const pendingReturn = useRef<string | null>(null);

  useEffect(() => {
    if (!entryIdFrom(window.history.state)) {
      window.history.replaceState({ ...window.history.state, [historyKey]: route.entryId }, '');
    }
  }, [route.entryId]);

  const saveVisit = useCallback(() => {
    visits.current.set(route.entryId, { filter, query, previewId, scrollTop: desk.current?.scrollTop ?? 0 });
  }, [route.entryId, filter, query, previewId]);

  const showRoute = useCallback((entryId: string, search: string, visit?: Visit) => {
    setRoute({ entryId, search, scrollTop: visit?.scrollTop ?? 0, moved: true });
    setFilter(visit?.filter ?? filterFrom(search));
    setQuery(visit?.query ?? '');
    setPreviewId(visit?.previewId);
  }, []);

  useEffect(() => {
    function onPopState(event: PopStateEvent) {
      pendingReturn.current = null;
      const entryId = entryIdFrom(event.state) ?? newEntryId();
      const search = window.location.search;
      if (entryId === route.entryId && search === route.search) return;
      saveVisit();
      if (!entryIdFrom(event.state)) {
        window.history.replaceState({ ...event.state, [historyKey]: entryId }, '');
      }
      showRoute(entryId, search, visits.current.get(entryId));
    }

    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [route, saveVisit, showRoute]);

  function navigate(event: MouseEvent<HTMLElement>) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    if (!(event.target instanceof Element)) return;
    const link = event.target.closest<HTMLAnchorElement>('a[data-workspace-link]');
    if (!link || (link.target && link.target !== '_self') || link.hasAttribute('download')) return;

    const url = new URL(link.href);
    if (url.origin !== window.location.origin || url.pathname !== window.location.pathname || url.hash) return;
    event.preventDefault();

    if (link.hasAttribute('data-return-to-journal') && requestsOpenedFromJournal.current.has(route.entryId)) {
      if (pendingReturn.current === route.entryId) return;
      pendingReturn.current = route.entryId;
      window.history.back();
      return;
    }

    if (url.search === route.search) {
      setFilter(filterFrom(url.search));
      setQuery('');
      setPreviewId(undefined);
      desk.current?.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      return;
    }

    saveVisit();
    const entryId = newEntryId();
    if (link.hasAttribute('data-opened-from-journal')) requestsOpenedFromJournal.current.add(entryId);
    window.history.pushState({ ...window.history.state, [historyKey]: entryId }, '', url);
    showRoute(entryId, url.search);
  }

  return { route, desk, filter, setFilter, query, setQuery, previewId, setPreviewId, navigate };
}
