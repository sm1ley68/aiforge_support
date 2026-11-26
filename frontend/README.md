# Store Advisor

Рабочее место сотрудника Softline Store для кейса «ИИкузница». React, TypeScript, Vite и Motion.

## Запуск

```sh
npm ci
npm run dev
```

В журнале можно искать запросы и фильтровать их по статусу и причине ручной проверки. Нажатие на строку открывает краткую карточку рядом с журналом. Кнопка «Полная карточка» открывает диалог, подбор и источники в текущей вкладке по отдельному адресу.

## Подключение API

Укажите адреса бекенда в `.env.local` и перезапустите Vite:

```dotenv
VITE_AGENT_API_URL=/api/consultation
VITE_AGENT_REQUESTS_URL=/api/requests
```

Адреса обслуживаются бекендом на том же origin или прокси. Для отдельного origin укажите полный URL и разрешите CORS на бекенде. Переменные доступны браузеру, поэтому указывайте только URL. При сборке для размещения задайте переменные до запуска `npm run build`.

Журнал делает JSON GET по `VITE_AGENT_REQUESTS_URL`. Ответ должен быть массивом `OperatorRequest` из `src/operator-types.ts`. Поле `response` содержит снимок диалога и результатов в формате `AgentResponse`. Если URL журнала не указан, используются данные `src/operator-mocks.ts`.

Окно «Тест агента» в боковой панели отправляет один JSON POST на сообщение по `VITE_AGENT_API_URL`:

```json
{
  "conversationId": null,
  "scenario": "known",
  "message": "Нужна Astra Linux",
  "history": [],
  "catalogProductId": "astra-linux-special-edition"
}
```

- `scenario` принимает значения `known`, `discovery`, `question` или `null`.
- `history` содержит предыдущие сообщения, каждое с полями `role` и `content`.
- `catalogProductId` берётся из параметра `?product=...` при переходе из каталога.
- В `reply` верните текст ассистента. Допустим также массив `messages`, из которого клиент покажет последнее сообщение ассистента.
- Ответ содержит ID диалога и данные для разбора обращения: `requirements`, `products`, `sources`, `trace`, `suggestedReplies`. Типы доступны в `src/agent-types.ts`.
- Логика обращения к API находится в `agent-client.mjs`. При пустом URL он вызывает `mock-agent.mjs` с тем же контрактом.
