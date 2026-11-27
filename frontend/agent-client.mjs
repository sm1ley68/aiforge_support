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

async function requestJson(fetchImpl, url, { method = 'GET', token, body, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetchImpl(url, { method, headers, body: JSON.stringify(body), signal });
  if (!response.ok) throw new Error(`Agent request failed (HTTP ${response.status}).`);
  return response.json();
}

function waitForPoll(signal) {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, 400);
    function onAbort() {
      clearTimeout(timer);
      reject(signal.reason);
    }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export function createAgentClient({ endpoint = '', mock, fetchImpl = globalThis.fetch } = {}) {
  const nativeRoute = /\/api\/consultation\/?$/;
  return {
    async send(request, { signal, attempt } = {}) {
      signal?.throwIfAborted();

      if (attempt && nativeRoute.test(endpoint)) {
        const base = endpoint.replace(nativeRoute, '');
        attempt.chat ??= await requestJson(fetchImpl, `${base}/chats`, { method: 'POST', signal });
        const { chat_id: chatId, chat_token: token } = attempt.chat;
        const chatPath = `${base}/chats/${encodeURIComponent(chatId)}`;
        if (!attempt.turnId) {
          const accepted = await requestJson(fetchImpl, `${chatPath}/messages`, {
            method: 'POST', token, signal,
            body: { client_message_id: attempt.messageId, text: request.message },
          });
          attempt.turnId = accepted.turn_id;
        }
        const turnPath = `turns/${encodeURIComponent(attempt.turnId)}`;
        while (true) {
          const turn = await requestJson(fetchImpl, `${chatPath}/${turnPath}`, { token, signal });
          if (turn.status === 'succeeded') {
            const payload = await requestJson(
              fetchImpl, `${base}/api/consultation/${encodeURIComponent(chatId)}/${turnPath}`, { token, signal },
            );
            return normalizeResponse(payload, chatId);
          }
          if (turn.status === 'failed') {
            delete attempt.turnId;
            attempt.messageId = newMessageId();
            throw new Error('Consultation turn failed.');
          }
          if (turn.status !== 'queued' && turn.status !== 'processing') throw new Error('Unexpected turn status.');
          await waitForPoll(signal);
        }
      }

      if (!endpoint && typeof mock !== 'function') {
        throw new TypeError('Configure an agent endpoint or provide a mock.');
      }
      const payload = endpoint
        ? await requestJson(fetchImpl, endpoint, { method: 'POST', body: request, signal })
        : await mock(request, { signal });
      signal?.throwIfAborted();
      return normalizeResponse(payload, request.conversationId);
    },
  };
}

export function newMessageId() {
  return globalThis.crypto.getRandomValues(new Uint32Array(4)).join('-');
}
