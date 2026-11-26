export type Scenario = 'known' | 'discovery' | 'question';

export type Message = {
  role: 'user' | 'assistant';
  content: string;
};

export type Requirement = { label: string; value: string };

export type Product = {
  id: string;
  name: string;
  version?: string;
  summary: string;
  detail?: string;
  features?: string[];
  url: string;
  recommended: boolean;
};

export type Source = { title: string; url: string; label?: string };
export type TraceStep = { label: string; detail: string };

export type AgentRequest = {
  conversationId: string | null;
  scenario: Scenario | null;
  message: string;
  history: Message[];
  catalogProductId?: string;
};

export type AgentResponse = {
  conversationId: string | null;
  messages: Message[];
  reply: string;
  requirements: Requirement[];
  products: Product[];
  sources: Source[];
  trace: TraceStep[];
  suggestedReplies: string[];
};
