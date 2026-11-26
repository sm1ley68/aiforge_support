import type { AgentRequest, AgentResponse } from './src/agent-types';

type Options = { signal?: AbortSignal };

export function createAgentClient(config?: {
  endpoint?: string;
  mock?: (request: AgentRequest, options: Options) => Promise<AgentResponse>;
  fetchImpl?: typeof fetch;
}): {
  send(request: AgentRequest, options?: Options): Promise<AgentResponse>;
};
