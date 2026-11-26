const byId = (id) => document.getElementById(id);

function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = content;
  if (className) node.className = className;
  return node;
}

async function request(path, { token, method = "GET", body } = {}) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!response.ok) throw new RequestError(response.status);
  return response.json();
}

class RequestError extends Error {
  constructor(status) {
    super("HTTP " + status);
    this.status = status;
  }
}

function feedback(node, message) {
  node.textContent = message;
  node.hidden = !message;
}

function sourceLink(url, title) {
  const link = element("a", title);
  try {
    const parsed = new URL(url);
    if (!["https:", "http:"].includes(parsed.protocol)) return element("span", title);
    link.href = parsed.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  } catch {
    return element("span", title);
  }
}

function sourceList(sources) {
  const list = element("ul", undefined, "source-list");
  for (const source of sources) {
    const item = element("li");
    item.append(sourceLink(source.url, source.title));
    list.append(item);
  }
  return list;
}

const reasons = {
  customer_requested: "Клиент запросил менеджера",
  insufficient_evidence: "Нужны подтверждённые сведения",
  commercial_terms: "Нужно уточнить коммерческие условия",
  provider_unavailable: "Сервис ответа недоступен",
};

function message(speaker, text, className) {
  const node = element("div", undefined, "message " + className);
  node.append(element("p", speaker, "speaker"), element("p", text));
  return node;
}

const chatSessionKey = "softline-demo-chat";
const turnStatus = {
  queued: "В очереди",
  processing: "Готовим ответ",
  failed: "Не удалось подготовить ответ.",
  succeeded: "Ответ готов",
};

function readChatSession() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(chatSessionKey));
    if (typeof saved?.chat_id === "string" && typeof saved?.chat_token === "string") return saved;
  } catch {
    // The chat can still be used when browser storage is unavailable.
  }
  return null;
}

function writeChatSession(session) {
  try {
    if (session) sessionStorage.setItem(chatSessionKey, JSON.stringify(session));
    else sessionStorage.removeItem(chatSessionKey);
  } catch {
    // The active credentials also live in memory.
  }
}

function productList(products) {
  const list = element("ul", undefined, "products");
  for (const product of products) {
    const item = element("li");
    const name = element("h3");
    name.append(sourceLink(product.url, product.title));
    const details = [
      product.sku ? "Артикул " + product.sku : null,
      product.price_amount != null && product.currency ? product.price_amount + " " + product.currency : null,
      product.availability === true ? "В наличии" : product.availability === false ? "Нет в наличии" : null,
    ].filter(Boolean);
    item.append(name);
    if (details.length) item.append(element("p", details.join(" · ")));
    if (product.match_summary) item.append(element("p", product.match_summary));
    if (product.verified_facts.length) {
      const facts = element("ul");
      for (const fact of product.verified_facts) {
        const row = element("li");
        row.append(sourceLink(fact.source.url, fact.field + " — " + fact.value));
        facts.append(row);
      }
      item.append(facts);
    }
    list.append(item);
  }
  return list;
}

function startChat() {
  const form = byId("chat-form");
  const input = byId("message");
  const send = byId("send");
  const list = byId("chat-messages");
  const newChat = byId("new-chat");
  const chatError = byId("chat-error");
  const timeline = new Map();
  let session = readChatSession();
  let draft;
  let timer;

  function syncEmptyState() {
    list.hidden = timeline.size === 0;
    byId("chat-empty").hidden = !list.hidden;
    newChat.hidden = !session;
  }

  function reset() {
    clearTimeout(timer);
    session = null;
    writeChatSession(null);
    draft = undefined;
    timeline.clear();
    list.replaceChildren();
    input.value = "";
    feedback(chatError, "");
    delete chatError.dataset.pollError;
    syncEmptyState();
    input.focus();
  }

  function addTurn(id, text, responseText) {
    if (timeline.has(id)) return;
    const item = element("li", undefined, "turn");
    item.dataset.turnId = id;
    const response = message("Поддержка", responseText || turnStatus.queued, "assistant");
    item.append(message("Вы", text, "customer"), response);
    list.append(item);
    timeline.set(id, { id, response, status: null });
    syncEmptyState();
  }

  function renderTurn(entry, turn) {
    const sameStatus = entry.status === turn.status;
    entry.status = turn.status;
    if (sameStatus) return;

    const response = entry.response;
    response.replaceChildren(element("p", "Поддержка", "speaker"));
    if (turn.status === "succeeded") {
      response.append(element("p", turn.text));
      if (turn.products.length) response.append(productList(turn.products));
      if (turn.sources.length) response.append(element("h3", "Источники"), sourceList(turn.sources));
    } else {
      const status = element("p", turnStatus[turn.status], turn.status === "failed" ? "error-text" : undefined);
      response.append(status);
      if (turn.status === "failed") {
        const retry = element("button", "Повторить", "secondary");
        retry.type = "button";
        retry.addEventListener("click", async () => {
          const active = session;
          retry.disabled = true;
          try {
            const current = await retryTurn(active, entry.id);
            if (active !== session) return;
            if (current.status === "failed") {
              status.textContent = "Повтор недоступен. Отправьте вопрос ещё раз.";
              retry.remove();
            } else {
              renderTurn(entry, current);
              schedulePoll();
            }
            input.focus();
          } catch {
            if (active !== session) return;
            retry.disabled = false;
            feedback(chatError, "Не удалось повторить запрос. Попробуйте ещё раз.");
          }
        });
        response.append(retry);
      }
    }
    byId("chat-announcement").textContent = turnStatus[turn.status];
  }

  function chatPath(active) {
    return "/chats/" + encodeURIComponent(active.chat_id);
  }

  function turnPath(active, id) {
    return chatPath(active) + "/turns/" + id;
  }

  async function retryTurn(active, id) {
    const path = turnPath(active, id);
    const token = active.chat_token;
    try {
      await request(path + "/retry", { token, method: "POST" });
      return { status: "queued" };
    } catch (error) {
      if (error.status !== 409) throw error;
      return request(path, { token });
    }
  }

  function schedulePoll() {
    clearTimeout(timer);
    timer = setTimeout(poll, 1100);
  }

  async function poll() {
    const active = session;
    if (!active || active.polling) return;
    const pending = [...timeline.values()].filter(({ status }) => status !== "succeeded" && status !== "failed");
    if (!pending.length) return;
    active.polling = true;
    try {
      const results = await Promise.all(pending.map((entry) => request(turnPath(active, entry.id), {
        token: active.chat_token,
      })));
      if (active !== session) return;
      for (const [index, result] of results.entries()) renderTurn(pending[index], result);
      if (chatError.dataset.pollError) {
        delete chatError.dataset.pollError;
        feedback(chatError, "");
      }
    } catch (error) {
      if (active !== session) return;
      if (error.status === 404) {
        reset();
        feedback(chatError, "Этот чат недоступен. Начните новый чат.");
        return;
      }
      if (!chatError.textContent) {
        chatError.dataset.pollError = "true";
        feedback(chatError, "Не удалось обновить переписку. Пробуем снова…");
      }
    } finally {
      active.polling = false;
      if (active === session) schedulePoll();
    }
  }

  async function restore(active) {
    send.disabled = true;
    newChat.disabled = true;
    try {
      const history = await request(chatPath(active) + "/messages", { token: active.chat_token });
      if (active !== session) return;
      const answers = new Map(history.filter((item) => item.role === "assistant").map((item) => [item.turn_id, item.text]));
      for (const item of history) {
        if (item.role === "user") addTurn(item.turn_id, item.text, answers.get(item.turn_id));
      }
      schedulePoll();
    } catch (error) {
      if (active !== session) return;
      if (error.status === 404) reset();
      else {
        feedback(chatError, "Не удалось загрузить историю. Обновите страницу, чтобы попробовать ещё раз.");
        return;
      }
    } finally {
      send.disabled = false;
      newChat.disabled = false;
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) {
      if (!text) feedback(chatError, "Напишите сообщение.");
      return;
    }
    send.disabled = true;
    input.readOnly = true;
    newChat.disabled = true;
    delete chatError.dataset.pollError;
    feedback(chatError, "");
    try {
      if (!session) {
        session = await request("/chats", { method: "POST" });
        writeChatSession(session);
        syncEmptyState();
      }
      if (draft?.text !== text) {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        const id = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
        draft = { client_message_id: id, text };
      }
      const result = await request(chatPath(session) + "/messages", {
        token: session.chat_token,
        method: "POST",
        body: draft,
      });
      addTurn(result.turn_id, text);
      input.value = "";
      draft = undefined;
      schedulePoll();
    } catch (error) {
      if (error.status === 404) feedback(chatError, "Этот чат недоступен. Начните новый чат.");
      else feedback(chatError, "Не удалось отправить сообщение. Попробуйте ещё раз.");
    } finally {
      send.disabled = false;
      input.readOnly = false;
      newChat.disabled = false;
      input.focus();
    }
  });

  byId("manager-example").addEventListener("click", () => {
    input.value = "Позовите менеджера";
    input.focus();
  });
  newChat.addEventListener("click", reset);
  syncEmptyState();
  if (session) restore(session);
}

function startManager() {
  const login = byId("manager-login");
  const password = byId("manager-token");
  const signIn = byId("manager-sign-in");
  const signOut = byId("manager-sign-out");
  const workspace = byId("manager-workspace");
  const queueList = byId("queue-list");
  const queueStatus = byId("queue-status");
  const detail = byId("case-detail");
  let session;
  let timer;
  let cases = [];
  let selected;

  function signOff(message) {
    clearTimeout(timer);
    session = undefined;
    cases = [];
    selected = undefined;
    password.value = "";
    login.hidden = false;
    signOut.hidden = true;
    workspace.hidden = true;
    queueList.replaceChildren();
    detail.removeAttribute("aria-busy");
    detail.replaceChildren(element("p", "Выберите обращение, чтобы посмотреть подробности и переписку."));
    feedback(byId("login-error"), message || "");
    password.focus();
  }

  function fillQueue(items) {
    const previousFocus = document.activeElement?.dataset.caseId;
    const rows = items.map((item) => {
      const row = element("li");
      const label = reasons[item.reason] || "Обращение";
      const button = element("button", label, "case-link");
      button.type = "button";
      button.dataset.caseId = item.handoff_id;
      button.setAttribute("aria-pressed", String(selected === item.handoff_id));
      button.append(element("span", item.summary.slice(0, 140)));
      button.addEventListener("click", () => openCase(item.handoff_id));
      row.append(button);
      return row;
    });
    queueList.replaceChildren(...rows);
    if (previousFocus) queueList.querySelector('[data-case-id="' + CSS.escape(previousFocus) + '"]')?.focus();
  }

  async function refresh(active) {
    if (active.refreshing) return;
    clearTimeout(timer);
    active.refreshing = true;
    try {
      const items = await request("/manager/handoffs", { token: active.token });
      if (active !== session) return;
      if (JSON.stringify(items) !== JSON.stringify(cases)) fillQueue(items);
      cases = items;
      const status = items.length ? "Обращений в очереди: " + items.length : "Очередь пока пуста.";
      if (queueStatus.textContent !== status) queueStatus.textContent = status;
      if (workspace.hidden) {
        login.hidden = true;
        signOut.hidden = false;
        workspace.hidden = false;
        byId("queue-refresh").focus();
      }
    } catch (error) {
      if (active !== session) return;
      if (error.status === 401 || error.status === 403) {
        signOff("Доступ не подтверждён. Проверьте токен менеджера.");
      } else if (workspace.hidden) {
        signOff("Не удалось открыть очередь. Попробуйте ещё раз.");
      } else {
        queueStatus.textContent = "Не удалось обновить очередь. Пробуем снова…";
      }
    } finally {
      active.refreshing = false;
      if (active === session) timer = setTimeout(() => refresh(active), 5000);
    }
  }

  async function openCase(id) {
    const active = session;
    selected = id;
    for (const button of queueList.querySelectorAll("[data-case-id]")) {
      button.setAttribute("aria-pressed", String(button.dataset.caseId === id));
    }
    detail.setAttribute("aria-busy", "true");
    detail.replaceChildren(element("p", "Загрузка…"));
    try {
      const item = await request("/manager/handoffs/" + id, { token: active.token });
      if (active !== session || id !== selected) return;
      const heading = element("h2", reasons[item.reason] || "Обращение");
      const overview = element("dl");
      for (const [key, value] of [
        ["Обращение", item.handoff_id],
        ["Чат", item.chat_id],
        ["Кандидаты", item.candidate_ids.join(", ")],
        ...Object.entries(item.requirements),
      ]) {
        if (value) overview.append(element("dt", key), element("dd", value));
      }
      detail.replaceChildren(heading, element("p", item.summary), overview);
      if (item.evidence.length) detail.append(element("h3", "Источники"), sourceList(item.evidence));
      const messages = element("ol", undefined, "case-messages");
      for (const entry of item.messages) {
        const row = element("li");
        row.append(message(entry.role === "user" ? "Клиент" : "Поддержка", entry.text, entry.role === "user" ? "customer" : "assistant"));
        messages.append(row);
      }
      detail.append(element("h3", "Переписка"), messages);
      detail.focus();
    } catch (error) {
      if (active !== session || id !== selected) return;
      if (error.status === 401 || error.status === 403) signOff("Введите токен менеджера.");
      else detail.replaceChildren(element("p", "Не удалось открыть обращение. Выберите его ещё раз."));
    } finally {
      if (active === session && id === selected) detail.removeAttribute("aria-busy");
    }
  }

  login.addEventListener("submit", async (event) => {
    event.preventDefault();
    const token = password.value.trim();
    if (!token || signIn.disabled) return;
    signIn.disabled = true;
    password.value = "";
    feedback(byId("login-error"), "");
    try {
      await request("/api/operator/session", { method: "POST", token });
      session = { token, refreshing: false };
      await refresh(session);
    } catch (error) {
      const message = error.status === 401 ? "Проверьте токен менеджера." : "Не удалось войти. Попробуйте ещё раз.";
      signOff(message);
    } finally {
      signIn.disabled = false;
    }
  });
  byId("queue-refresh").addEventListener("click", () => {
    if (session) refresh(session);
  });
  signOut.addEventListener("click", async () => {
    try {
      await request("/api/operator/session", { method: "DELETE" });
      signOff();
    } catch {
      queueStatus.textContent = "Не удалось завершить сеанс. Попробуйте выйти ещё раз.";
    }
  });
}

if (document.body.dataset.screen === "chat") startChat();
if (document.body.dataset.screen === "manager") startManager();
