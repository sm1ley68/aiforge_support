<div align="center">

# Softline Store Advisor

**ИИ-агент поддержки B2B-магазина Softline**

Подбор ПО, проверка сведений о товаре и коммерческие предложения в одном чате.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](Dockerfile)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)](docs/softline-catalog-chat.md)
[![React](https://img.shields.io/badge/React-TypeScript-087EA4?logo=react&logoColor=white)](frontend/README.md)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](compose.yaml)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](compose.yaml)

**[Онлайн-стенд](#онлайн-стенд) · [Архитектура](#как-устроена-система) · [Результаты](#как-проверяли)**

</div>

---

## Онлайн-стенд

| Где | Адрес |
| --- | --- |
| Клиентский чат | [Открыть чат клиента](https://129.101.119.168:8443/advisor?view=chat) |
| Кабинет менеджера | [Открыть журнал обращений](https://129.101.119.168:8443/advisor?view=journal) |

Для входа в кабинет нужен ключ онлайн-стенда. При действующей сессии повторный ввод не требуется.

<details>
<summary>Локальный запуск через Docker</summary>

> **Демо запускается без ключа к модели.** Тестовый каталог уже в репозитории.

Понадобятся **Docker с Compose v2**, **Node.js 22.12+ с npm** и Git. Команды рассчитаны на macOS, Linux или WSL.

### 1. Склонируйте проект и соберите интерфейс

```sh
git clone https://github.com/sm1ley68/aiforge_support.git
cd aiforge_support
npm ci --prefix frontend
npm run build --prefix frontend
```

### 2. Подготовьте каталог и запустите стенд

Выполните из корня репозитория. Compose создаст отдельную PostgreSQL, API и worker. Индекс каталога собирается из двух тестовых товаров.

```sh
RUN_DIR=ml_pipeline/.local/jury
mkdir -p "$RUN_DIR"
cat > "$RUN_DIR/compose.env" <<'ENV'
COMPOSE_PROJECT_NAME=aiforge-jury
PORT=8080
CATALOG_DIR=./ml_pipeline/.local/jury
COMMERCE_CATALOG_INDEX_PATH=/catalog/commerce.sqlite3
STORE_ADVISOR_DIST_DIR=./frontend/dist
STORE_ADVISOR_DIST_PATH=/advisor-dist
MANAGER_TOKEN=jury-local-demo
COMMERCE_MODEL_PROFILE=offline
POLZA_EGRESS_MODE=disabled
COMMERCE_VERIFY_SITE_CARD=disabled
ENV

docker compose --env-file "$RUN_DIR/compose.env" build api worker
if [ ! -f "$RUN_DIR/commerce.sqlite3" ]; then
  docker compose --env-file "$RUN_DIR/compose.env" run --rm --no-deps \
    --user "$(id -u):$(id -g)" \
    --volume "$PWD/fixtures/softline:/fixture:ro" \
    --volume "$PWD/$RUN_DIR:/out" \
    api python -m aisupport_ml.commerce.catalog \
    /fixture/advisor-acceptance.xml /out/commerce.sqlite3
fi
chmod a+r "$RUN_DIR/commerce.sqlite3"
docker compose --env-file "$RUN_DIR/compose.env" up -d --wait
curl -fsS http://127.0.0.1:8080/health/ready
```

После запуска откройте [чат](http://127.0.0.1:8080/advisor?view=chat) или [журнал менеджера](http://127.0.0.1:8080/advisor?view=journal). Ключ локального журнала — `jury-local-demo`.

### Остановка стенда

Остановить локальное демо можно из корня репозитория. Данные для следующего запуска хранятся в томе PostgreSQL.

```sh
docker compose --env-file ml_pipeline/.local/jury/compose.env down
```

</details>

---

## О проекте

Проект команды **Slightly Overqualified** для кейса «ИИкузница». Покупатель получает консультацию в веб-чате, а менеджер работает с переданными обращениями в отдельном кабинете.

| Сценарий | Что делает агент |
| --- | --- |
| Покупатель знает продукт | Находит предложение по артикулу или названию, сверяет редакцию, срок, размер пакета и наличие. |
| Покупатель описывает задачу | Уточняет платформу, количество и бюджет. Проверенные сценарии покрывают защиту почты и файлов, резервное копирование и планирование проектов. |
| Нужно коммерческое предложение | Рассчитывает КП по подтверждённой цене. Запросы об индивидуальной скидке или проверке поставки направляет менеджеру. |
| Нужна помощь после покупки | Находит инструкции о ключах, документах и ЭДО. Подбирает опубликованные ответы менеджера по смыслу вопроса и привязке к товару. |

## Как устроена система

```mermaid
flowchart LR
    UI["Веб-чат и кабинет менеджера"] --> API["FastAPI"]
    API --> DB[("PostgreSQL · история и очередь")]
    DB <--> W["Worker и CommerceAgent"]
    W --> CAT[("SQLite · каталог")]
    W --> KB["Карточки товаров и проверенные статьи"]
    W --> F["Локальный фильтр"]
    F --> H["Haiku через Polza"]
    F --> Q["Qwen через Ollama"]
```

Интерфейс написан на React и TypeScript с Vite. API сохраняет ход в PostgreSQL, worker обрабатывает его и возвращает текст, карточки и источники. Для конкретной позиции агент может свериться с карточкой сайта по точному SKU и редакции. Фид хранит дату снимка. Если существенный факт подтвердить не удаётся, менеджер получает вопрос и ссылки на доступные источники.

Модель извлекает структурированные параметры запроса. SKU, цена, наличие и правила передачи опираются на каталог и проверяемую логику. Через фильтр к модели проходят разрешённые технические поля. Сырой текст чата, история и реквизиты остаются в серверном контуре. [Локальный фильтр](docs/llm-privacy.md)

## Каталог и модели

В быстром старте используется [тестовый каталог](fixtures/softline/advisor-acceptance.xml). Для проверки подбора на полном каталоге соберите отдельный Commerce-индекс из доступной вам выгрузки Softline в формате YML/XML. Подключите каталог индекса через `CATALOG_DIR`, а файл внутри контейнера через `COMMERCE_CATALOG_INDEX_PATH`. [Импорт и обновление каталога](docs/softline-catalog-chat.md)

| Профиль | Когда использовать |
| --- | --- |
| `offline` | Воспроизводимое демо с локальным каталогом, статьями и правилами. |
| `polza` | Haiku на сервере. Установите `COMMERCE_MODEL_PROFILE=polza`, `POLZA_EGRESS_MODE=real` и добавьте свой ключ в локальную настройку `POLZA_API_KEY`. |
| `qwen-local` | Локальный Ollama. Для проверенной модели на 4B укажите `COMMERCE_OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M` и загрузите веса командой ниже. |

```sh
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Qwen 4B занимает **около 2,5 ГБ на диске**. Ollama хранит веса отдельно. Профиль выбирается при запуске worker. Для одновременного показа двух моделей используйте отдельные стенды. [Настройки профилей и Compose для Ollama](docs/softline-model-profiles.md)

## Как проверяли

Оба профиля проверили на одной закрытой синтетической выборке из **8 диалогов и 21 реплики**.

| Метрика | Haiku | Qwen 4B |
| --- | ---: | ---: |
| Диалоги без ошибок | 8/8 | 8/8 |
| Успешные вызовы модели | 4/4 | 4/4 |
| Верный SKU или ожидаемое отсутствие позиции | 13/13 | 13/13 |
| Ожидаемые факты и источники | 13/13 | 13/13 |
| Передачи менеджеру с историей | 3/3 | 3/3 |
| p95 по всем репликам | 2,99 с | 7,72 с |

<div align="center">
<img src="ml_pipeline/agent_eval/figures/profile-comparison.png" alt="Задержка Haiku и Qwen по всему ходу и отдельно на вызовах модели" width="85%">
<br>
<sub>Задержка по 21 реплике и четырём вызовам каждой модели. Qwen запущена локально на Apple M3.</sub>
</div>

Результаты относятся к синтетическим сценариям. [Протокол и подробные замеры](docs/softline-model-profile-results.md)

Интеграционные тесты используют отдельную PostgreSQL. Выполните из корня проекта.

```sh
python -m pip install '.[backend,backend-test,catalog,privacy]' pytest
TEST_DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/TEST_DB python -m pytest -q
```

## Структура репозитория

```text
aiforge_support/
├── frontend/          # Клиентский чат и кабинет менеджера
├── softline_backend/  # FastAPI, worker и PostgreSQL
├── aisupport_ml/      # Агент, каталог и фильтрация запросов
├── fixtures/softline/ # Данные для локального запуска
├── ml_pipeline/      # Сценарии и результаты проверок
└── docs/             # Руководства по запуску и интеграции
```

## Документация

- [API, импорт каталога и запуск worker](docs/softline-catalog-chat.md)
- [Разработка фронтенда и сценарии приёмки](frontend/README.md)
- [Структура доступа к источникам и фильтрация перед вызовом модели](docs/llm-privacy.md)
- [Проверка стенда через HTTP](docs/softline-acceptance.md)
