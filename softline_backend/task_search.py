import re
from dataclasses import replace
from pathlib import Path

from .catalog import find_task_cards
from .contracts import MessageView, TurnResult
from .task_extraction import TaskExtraction, TaskExtractor
from .task_recommendation import TaskRequest, catalog_sources, recommend_task, request_fields
from .task_vocabulary import Capability


TASK = re.compile(r"подбери(?:те)?\s+(?:решение для\s+)?(.+)")
PROTECTION_TASK = re.compile(
    r"(?:не знаю(?:, что нужно)?, (?:но )?)?(?:нужна защита|(?:хотим|нужно|надо) защитить)\s+(.+)"
)
USERS = re.compile(
    r"(?:на|для)\s+([1-9][0-9]{0,6})\s+(?:пользовател(?:ей|я|ь)|сотрудник(?:ов|а)?|человек)"
)
BUDGET = re.compile(
    r"(?:бюджет(?: снизился| вырос)?(?: до)?|до)\s+"
    r"([0-9]{1,3}(?: [0-9]{3}){1,3}|[0-9]{1,12})"
    r"(?:\s*(?:₽|руб(?:ль|ля|лей)?\.?))?"
)
RUSSIAN = re.compile(
    r"(?:а )?(?:(?:покажи(?:те)?|подбери(?:те)?|есть(?: ли)?)\s+)?(?:российский|отечественный)\s+аналог"
)
STOPWORDS = {"и", "или", "для", "на", "от", "по", "с", "за", "в", "из"}
PREFIXES = ("защит", "почт", "файл")
SIMPLE_PROTECTION = r"защит[ауыеи]"
MAIL = r"(?:электронн(?:ой|ую) )?почт[уы]"
FILES = r"файл(?:ы|ов)"


def _local_capabilities(query: str) -> tuple[Capability, ...]:
    if re.fullmatch(rf"{SIMPLE_PROTECTION} (?:{MAIL} и {FILES}|{FILES} и {MAIL})", query):
        return ("email_protection", "file_protection")
    if re.fullmatch(rf"{SIMPLE_PROTECTION} {MAIL}", query):
        return ("email_protection",)
    if re.fullmatch(rf"{SIMPLE_PROTECTION} {FILES}", query):
        return ("file_protection",)
    return ()


def _normalize(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split()).rstrip(".?!")


def _changes(text: str) -> dict:
    if users := USERS.fullmatch(text):
        return {"user_limit": int(users[1])}
    if budget := BUDGET.fullmatch(text):
        return {"budget_kopecks": int(budget[1].replace(" ", "")) * 100}
    if text in {"локально", "только локально", "локальное развертывание", "только on-premise"}:
        return {"deployment": "локально"}
    if text in {"облако", "только облако", "только в облаке", "облачное развертывание"}:
        return {"deployment": "облако"}
    if RUSSIAN.fullmatch(text):
        return {"origin": "Россия"}
    return {}


def _new_task(text: str) -> TaskRequest | None:
    if protection := PROTECTION_TASK.fullmatch(text):
        text = f"подбери защита {protection[1]}"
    root = TASK.fullmatch(text)
    if root is None or RUSSIAN.fullmatch(text):
        return None

    query, *filters = (chunk.strip() for chunk in root[1].split(","))
    changes = {}
    for possible_filter in filters:
        recognized = _changes(possible_filter)
        if not recognized:
            query += f" {possible_filter}"
        changes.update(recognized)

    users = re.search(rf"\s+{USERS.pattern}$", query)
    if users:
        changes["user_limit"] = int(users[1])
        query = query[:users.start()]
    return TaskRequest(query, **changes, capabilities=_local_capabilities(query))


def _request(text: str, history: list[MessageView]) -> TaskRequest | None:
    normalized = _normalize(text)
    if task := _new_task(normalized):
        return task
    pending = _changes(normalized)
    if not pending:
        return None

    for message in reversed(history):
        if message.role != "user":
            continue
        previous = _normalize(message.text)
        if task := _new_task(previous):
            return replace(task, **pending)
        changes = _changes(previous)
        if not changes:
            return None
        pending = changes | pending
    return None


def _match_expression(query: str) -> str | None:
    words = list(dict.fromkeys(re.findall(r"[^\W_]+", query)))
    terms = []
    for word in words:
        if word in STOPWORDS:
            continue
        prefix = next((item for item in PREFIXES if word.startswith(item)), None)
        terms.append(f'"{prefix}"*' if prefix else f'"{word}"')
    if 1 <= len(terms) <= 12:
        return " AND ".join(dict.fromkeys(terms))
    return None


def _merge_extraction(local: TaskRequest | None, extracted: TaskExtraction, text: str) -> TaskRequest:
    budget = extracted.budget_rubles
    supplied = _changes(_normalize(text))
    request = TaskRequest(
        query=" ".join(extracted.terms),
        user_limit=extracted.user_limit,
        deployment=extracted.deployment,
        budget_kopecks=budget * 100 if budget is not None else None,
        origin=extracted.origin,
        capabilities=tuple(dict.fromkeys(extracted.capabilities)),
    )
    if local is not None:
        request = replace(
            request,
            query=request.query or local.query,
            user_limit=local.user_limit if local.user_limit is not None else request.user_limit,
            deployment=local.deployment or request.deployment,
            budget_kopecks=local.budget_kopecks if local.budget_kopecks is not None else request.budget_kopecks,
            origin=local.origin or request.origin,
            capabilities=local.capabilities or request.capabilities,
        )
    return replace(request, **supplied)


def _extraction_history(text: str, history: list[MessageView]) -> list[MessageView]:
    if _new_task(_normalize(text)) is not None:
        return []
    for offset, message in enumerate(reversed(history), 1):
        if message.role == "user" and _new_task(_normalize(message.text)) is not None:
            return history[-offset:]
    return history


def task_reply(
    index: Path,
    text: str,
    history: list[MessageView],
    *,
    extractor: TaskExtractor | None = None,
) -> TurnResult | None:
    request = _request(text, history)
    if extractor is not None:
        extracted = extractor(text, _extraction_history(text, history))
        if extracted is not None:
            if extracted.intent == "clarify":
                question = (
                    "Уточните назначение продукта несколькими словами."
                    if extracted.missing == "purpose"
                    else "Уточните обязательные условия, которым должно соответствовать решение."
                )
                return TurnResult(outcome="clarify", text=question)
            if extracted.intent == "task":
                request = _merge_extraction(request, extracted, text)
    if request is None:
        return None
    if verified := recommend_task(index, request):
        return verified
    expression = _match_expression(request.query)
    if expression is None:
        return TurnResult(outcome="clarify", text="Уточните назначение продукта несколькими словами.")

    cards = find_task_cards(
        index,
        expression,
        user_limit=request.user_limit,
        deployment=request.deployment,
        budget_kopecks=request.budget_kopecks,
        origin=request.origin,
    )
    if cards is None:
        return TurnResult(outcome="clarify", text="Для поиска по задаче нужно обновить снимок каталога.")
    if not cards:
        return TurnResult(
            outcome="clarify",
            text="В снимке нет доступных предложений с подтверждёнными ограничениями и всеми терминами задачи.",
        )

    constraints = []
    if request.user_limit is not None:
        constraints.append(f"от {request.user_limit} пользователей")
    if request.deployment:
        constraints.append(f"развёртывание: {request.deployment}")
    if request.origin:
        constraints.append(f"происхождение: {request.origin}")

    message = "Нашёл доступные предложения по словам из задачи. Проверьте описание и условия лицензии по ссылкам."
    if constraints:
        message += " Подтверждённые ограничения: " + ", ".join(constraints) + "."
    if request.budget_kopecks is not None:
        amount = f"{request.budget_kopecks // 100:,}".replace(",", " ")
        message += f" Цена каждой позиции в снимке укладывается в {amount} ₽. Общая стоимость лицензий требует уточнения."
    return TurnResult(
        outcome="answer",
        text=message,
        products=cards,
        sources=catalog_sources(cards, request_fields(request)),
    )
