import type { AgentResponse, Scenario } from './agent-types';

export type OperatorStatus = 'review' | 'waiting' | 'resolved';

export type RequestComparisonRow = {
  label: string;
  value?: string;
  result: string;
  state: 'match' | 'review' | 'missing';
  detail?: string;
  sourceUrl?: string;
};

export type OperatorRequest = {
  id: string;
  handoffId?: string;
  title: string;
  customer: string;
  updatedAt: string;
  scenario: Scenario;
  status: OperatorStatus;
  issue?: { label: string; detail: string; checks?: string[] };
  comparison?: { productId: string; rows: RequestComparisonRow[] };
  response: AgentResponse;
};
