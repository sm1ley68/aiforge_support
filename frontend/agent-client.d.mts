import type { AgentRequest, AgentResponse } from './src/agent-types';

export type ConsultationAttempt = {
  messageId: string;
  chat?: { chat_id: string; chat_token: string };
  turnId?: string;
};
type Options = { signal?: AbortSignal; attempt?: ConsultationAttempt };

export function newMessageId(): string;

export function createAgentClient(config?: {
  endpoint?: string;
  mock?: (request: AgentRequest, options: Options) => Promise<AgentResponse>;
  fetchImpl?: typeof fetch;
}): {
  send(request: AgentRequest, options?: Options): Promise<AgentResponse>;
};
