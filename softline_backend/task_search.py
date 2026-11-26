import re
from dataclasses import dataclass, replace
from pathlib import Path

from .catalog import find_task_cards
from .contracts import MessageView, Source, TurnResult


TASK = re.compile(r"подбери(?:те)?\s+(?:решение для\s+)?(.+)")
PROTECTION_TASK = re.compile(r"(?:нужна защита|хотим защитить)\s+(.+)")
USERS = re.compile(r"на\s+([1-9][0-9]{0,6})\s+(?:пользовател(?:ей|я|ь)|сотрудник(?:ов|а)?)")
BUDGET = re.compile(
    r"(?:бюджет(?: снизился| вырос)?(?: до)?|до)\s+"
    r"([0-9]{1,3}(?: [0-9]{3}){1,3}|[0-9]{1,12})"
    r"(?:\s*(?:₽|руб(?:ль|ля|лей)?\.?))?"
)
RUSSIAN = re.compile(r"(?:(?:покажи(?:те)?|подбери(?:те)?|есть)\s+)?(?:российский|отечественный)\s+аналог")
STOPWORDS = {"и", "или", "для", "на", "от", "по", "с", "за", "в", "из"}
PREFIXES = ("защит", "почт", "файл")


@dataclass(frozen=True)
class TaskRequest:
    query: str
    user_limit: int | None = None
    deployment: str | None = None
    budget_kopecks: int | None = None
    origin: str | None = None


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
    return TaskRequest(query, **changes)


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


def task_reply(index: Path, text: str, history: list[MessageView]) -> TurnResult | None:
    request = _request(text, history)
    if request is None:
        return None
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
    if request.budget_kopecks is not None:
        constraints.append(f"цена позиции до {request.budget_kopecks // 100:,} ₽".replace(",", " "))
    if request.origin:
        constraints.append(f"происхождение: {request.origin}")

    message = "Нашёл доступные предложения по словам из задачи. Проверьте описание и условия лицензии по ссылкам."
    if constraints:
        message += " Подтверждённые ограничения: " + ", ".join(constraints) + "."
    return TurnResult(
        outcome="answer",
        text=message,
        products=cards,
        sources=[Source(title=card.title, url=card.url) for card in cards],
    )
