import type { AgentRequest, AgentResponse } from './src/agent-types';

export const demoConversation: AgentResponse;
export function mockAgent(request: AgentRequest, options?: { signal?: AbortSignal }): Promise<AgentResponse>;
