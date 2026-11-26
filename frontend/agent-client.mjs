function normalizeResponse(response, conversationId) {
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new TypeError('The agent response must be a JSON object.');
  }

  return {
    conversationId: response.conversationId ?? conversationId ?? null,
    messages: response.messages ?? [],
    reply: response.reply ?? '',
    requirements: response.requirements ?? [],
    products: response.products ?? [],
    sources: response.sources ?? [],
    trace: response.trace ?? [],
    suggestedReplies: response.suggestedReplies ?? [],
  };
}

export function createAgentClient({ endpoint = '', mock, fetchImpl = globalThis.fetch } = {}) {
  return {
    async send(request, { signal } = {}) {
      signal?.throwIfAborted();

      if (!endpoint) {
        if (typeof mock !== 'function') {
          throw new TypeError('Configure an agent endpoint or provide a mock.');
        }

        const response = await mock(request, { signal });
        signal?.throwIfAborted();
        return normalizeResponse(response, request.conversationId);
      }

      const response = await fetchImpl(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(request),
        signal,
      });

      if (!response.ok) {
        const error = new Error(`Agent request failed (HTTP ${response.status}).`);
        error.status = response.status;
        throw error;
      }

      const payload = await response.json();
      signal?.throwIfAborted();
      return normalizeResponse(payload, request.conversationId);
    },
  };
}
