# Профили модели для Softline Store Advisor

Выбирайте профиль в worker через `COMMERCE_MODEL_PROFILE`.

| Профиль | Модель | Подключение |
| --- | --- | --- |
| `haiku` (по умолчанию) | `anthropic/claude-haiku-5.5` | Polza через штатный фильтр, `POLZA_EGRESS_MODE=real` и существующий ключ |
| `ollama` | Qwen3-4B-Instruct-2507, `Q4_K_M` | Ollama на том же хосте или в закрытой сети Compose |
| `offline` | Правила и локальный каталог | Вызовы модельного сервера отключены |

Публичный контракт чата для всех профилей одинаковый. Обе модели получают техническую фразу с разрешёнными полями. Возвращаемый JSON содержит ровно семь ключей.

```json
{
  "action": "need",
  "fact": null,
  "product": null,
  "edition": null,
  "goal": "защитить почту и файлы",
  "mail": "Exchange",
  "file_os": "Windows Server 2022"
}
```

Worker проверяет JSON и сверяет значения с техническими полями запроса. Цены, SKU, наличие, источники и основания для передачи менеджеру обрабатывает сам агент на основании каталога и статей. При недоступности модели включается существующий локальный маршрут. В журнал попадают длительность, статус и счётчики токенов. Тексты обращений остаются в серверном контуре.

## Запуск на macOS или Linux

Qwen распространяет [исходные веса под Apache 2.0](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/LICENSE). Выбранный [вариант Ollama](https://ollama.com/library/qwen3%3A4b-instruct-2507-q4_K_M) занимает 2,50 ГБ на диске. В прогоне на Apple M3 с 8 ГБ единой памяти Ollama показал 3,20 ГБ памяти модели на GPU при контексте 2 048 токенов и одном запросе за раз. Загрузка и скорость на другом оборудовании зависят от драйвера и настройки параллелизма.

Запустите Ollama 0.12.10 или совместимую версию в отдельном терминале.

```sh
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=2048 \
  OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

Загрузите веса и прогрейте модель.

```sh
ollama pull qwen3:4b-instruct-2507-q4_K_M
curl -fsS http://127.0.0.1:11434/api/generate -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:4b-instruct-2507-q4_K_M","stream":false,"keep_alive":"10m","options":{"num_ctx":2048}}'
ollama ps
```

Для воспроизведения сравнения сверьте digest в `/api/tags` с `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.

Перезапустите штатный worker рядом с Ollama. API и PostgreSQL продолжают работать с тем же `DATABASE_URL`. `COMMERCE_CATALOG_INDEX_PATH` должен указывать на SQLite, подготовленный модулем `aisupport_ml.commerce.catalog`.

```sh
python -m pip install '.[backend,privacy]'
COMMERCE_MODEL_PROFILE=ollama COMMERCE_OLLAMA_URL=http://127.0.0.1:11434 \
  COMMERCE_CATALOG_INDEX_PATH=/absolute/path/to/catalog.sqlite POLZA_EGRESS_MODE=disabled \
  python -m softline_backend.worker
```

Для быстрой проверки спросите в чате «Для нового филиала потребуется защитить почту и файлы на 36 устройствах. Exchange, Windows Server 2019, локально. Бюджет до 300000 рублей». При доступном каталоге в ответе появится `KL4869RAPFS`. Строка `ollama_extraction ... status=ok` в журнале подтверждает, что модель действительно обработала ход.

## Профиль Docker Compose

Сначала скачайте веса в том проекта. В примере используется имя проекта `aiforge`. Временный контейнер скачивает модель до запуска закрытой сети.

```sh
docker volume create aiforge_ollama-models
docker run --rm -v aiforge_ollama-models:/root/.ollama \
  --entrypoint /bin/sh ollama/ollama:0.12.10 -ec '
    ollama serve & server=$!
    trap "kill $server" EXIT
    until ollama list >/dev/null 2>&1; do sleep 1; done
    ollama pull qwen3:4b-instruct-2507-q4_K_M
  '
docker compose -p aiforge -f compose.yaml -f compose.ollama.yaml up -d --build
docker compose -p aiforge -f compose.yaml -f compose.ollama.yaml exec ollama ollama list
```

Модельный сервис доступен worker по адресу `http://ollama:11434` без публичного порта. Для GPU на сервере добавьте проброс согласно настройкам его Docker и драйвера. На Mac нативный Ollama использует Metal.

## Публикация и поиск ответов менеджера

Worker использует опубликованные статьи из существующего маршрута `POST /api/requests/{handoff_id}/knowledge`. При точном совпадении продолжают работать вопрос и варианты формулировок. Если точного совпадения нет, локальный поиск сравнивает нормальные формы и близкие по смыслу слова. Ответ возвращается только при высоком покрытии слов и явном отрыве от второго результата. Для статьи с SKU нужна однозначная позиция из текущего запроса или явно указанная клиентом карточка из последнего ответа. Приватная реплика менеджера в поиске не участвует.
