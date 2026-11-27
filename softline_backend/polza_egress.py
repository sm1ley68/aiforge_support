import asyncio
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass, replace
from importlib.util import find_spec
from threading import Lock
from typing import Annotated, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aisupport_ml.contracts import TemporaryReadError
from aisupport_ml.privacy import prepare_llm_input


logger = logging.getLogger(__name__)
FILTER_TIMEOUT_SECONDS = 1
ENDPOINT = "https://polza.ai/api/v1/chat/completions"
SYSTEM = """Заполни все поля JSON по схеме. Вход — техническая фраза с фиксированными формулировками.
Если фраза начинается с «Нужно резервное копирование» или «Нужно защитить почту и файлы»,
поставь action="need", а в goal дословно скопируй «резервное копирование» или «защитить почту и файлы».
В goal не включай количество, платформу, способ развёртывания или слово «Нужно».
Если фраза начинается с «Технические условия», поставь action="continue" и goal=null.
В file_os скопируй точное название и версию ОС из фразы, без предлогов и исправлений.
В mail укажи Exchange только при явном «почтовая система Exchange». Если поля нет во фразе, верни null.
Всегда возвращай null в полях fact, product и edition."""
RESPONSE_FIELDS = {"action", "fact", "product", "edition", "goal", "mail", "file_os"}
TASKS = {"backup": "резервное копирование", "email_file_security": "защитить почту и файлы"}
PLATFORMS = {
    "windows_10": "Windows 10",
    "windows_11": "Windows 11",
    "windows_server_2016": "Windows Server 2016",
    "windows_server_2019": "Windows Server 2019",
    "windows_server_2022": "Windows Server 2022",
    "linux": "Linux",
    "macos": "macOS",
}
DEPLOYMENTS = {"local": "локально", "cloud": "в облаке"}
MAIL_SYSTEMS = {"exchange": "Exchange"}
SENSITIVE = re.compile(
    r"\b[\w.+-]+@[\w.-]+\.[\w]{2,}\b"
    r"|(?<!\w)\+?[78](?:[\s().-]*\d){10}(?!\w)"
    r"|\b(?:\d{1,3}\.){3}\d{1,3}\b"
    r"|\[(?:фио|имя|телефон|почта|адрес|паспорт|email|phone|name|address)\]"
    r"|\b(?:инн|снилс|паспорт|номер заказа)\s*[:№#]?\s*[a-zа-я0-9-]{4,}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TurnScope:
    turn_id: str
    message: str
    history: tuple[str, ...]
    stored_state: dict | None
    selection: dict | None = None


polza_scope: ContextVar[TurnScope | None] = ContextVar("polza_scope", default=None)


class TechnicalFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task: Literal["backup", "email_file_security"] | None = None
    platform: Literal[
        "windows_10", "windows_11", "windows_server_2016", "windows_server_2019",
        "windows_server_2022", "linux", "macos",
    ] | None = None
    device_count: Annotated[int, Field(ge=1, le=99999)] | None = None
    license_count: Annotated[int, Field(ge=1, le=99999)] | None = None
    deployment: Literal["local", "cloud"] | None = None
    mail: Literal["exchange"] | None = None


class FilterDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["allow", "block", "uncertain"]
    fields: TechnicalFields | None = None
    cleaned_text: str | None = Field(default=None, max_length=8000)


LocalFilter = Callable[[TurnScope], Awaitable[dict | FilterDecision]]


class EgressBlocked(TemporaryReadError):
    pass


def record(decision: str, category: str) -> None:
    scope = polza_scope.get()
    logger.info(
        "polza_egress turn_id=%s decision=%s category=%s",
        scope.turn_id if scope else "-", decision, category,
    )


def block(category: str) -> NoReturn:
    record("blocked", category)
    raise EgressBlocked("External extraction is unavailable")


_privacy_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-privacy")
_privacy_slot = Lock()


def _screen_with_ml(scope: TurnScope) -> dict:
    stored = scope.stored_state or {}
    if stored.get("support_topic") not in (None, "keys", "activation", "returns"):
        return {"decision": "uncertain"}
    if any(value for key, value in stored.items() if key not in {"catalog_context", "support_topic"}):
        return {"decision": "uncertain"}
    stored_selection = stored.get("catalog_context")
    if isinstance(stored_selection, dict):
        stored_selection = {"license_action": None, "unverified_constraint": False, **stored_selection}
    if json.dumps(stored_selection, sort_keys=True) != json.dumps(scope.selection, sort_keys=True):
        return {"decision": "uncertain"}

    checked = prepare_llm_input(scope.message, history=scope.history, selection=scope.selection)
    if checked.categories:
        return {"decision": "block"}
    if checked.model_payload is None:
        return {"decision": "uncertain"}
    return {"decision": "allow", "fields": checked.model_payload}


async def _native_filter(scope: TurnScope) -> dict:
    if not _privacy_slot.acquire(blocking=False):
        return {"decision": "uncertain"}
    try:
        work = _privacy_worker.submit(_screen_with_ml, scope)
    except Exception:
        _privacy_slot.release()
        raise
    work.add_done_callback(lambda _: _privacy_slot.release())
    return await asyncio.wrap_future(work)


def load_egress_filter() -> tuple[bool, LocalFilter | None]:
    enabled = os.getenv("POLZA_EGRESS_MODE", "") == "real"
    if not enabled:
        return False, None
    return True, _native_filter if find_spec("natasha") is not None else None


def _has_sensitive(value) -> bool:
    if isinstance(value, str):
        return bool(SENSITIVE.search(value))
    if isinstance(value, dict):
        return any(_has_sensitive(key) or _has_sensitive(item) for key, item in value.items())
    if isinstance(value, (tuple, list)):
        return any(map(_has_sensitive, value))
    if type(value) is int:
        return bool(SENSITIVE.search(str(value)))
    return False


@dataclass(frozen=True)
class PreparedPrompt:
    text: str
    goal: str | None
    platform: str | None
    mail: str | None

    def validate_answer(self, result: dict, *, reject=block) -> dict:
        if not isinstance(result, dict) or result.keys() != RESPONSE_FIELDS:
            reject("response_fields")
        if result["action"] not in ("need", "continue", "other"):
            reject("response_action")
        allowed = {
            "fact": None, "product": None, "edition": None,
            "goal": self.goal, "mail": self.mail, "file_os": self.platform,
        }
        for key, expected in allowed.items():
            value = result[key]
            if value is not None and (
                not isinstance(value, str) or expected is None or value.casefold() != expected.casefold()
            ):
                reject(f"response_{key}")
        if result["action"] == "need" and result["goal"] is None:
            reject("response_goal_missing")
        return result


async def prepare(model_input: str, checker: LocalFilter, *, reject=block) -> PreparedPrompt:
    scope = polza_scope.get()
    if scope is None:
        reject("missing_turn_scope")
    try:
        candidate = json.loads(model_input)
    except (TypeError, ValueError, RecursionError):
        reject("invalid_candidate")
    if (
        not isinstance(candidate, dict) or candidate.keys() != {"message", "selection"}
        or not isinstance(candidate["message"], str) or candidate["message"] != scope.message.strip()
        or (candidate["selection"] is not None and not isinstance(candidate["selection"], dict))
    ):
        reject("invalid_candidate")
    scope = replace(scope, selection=candidate["selection"])
    if _has_sensitive((scope.message, scope.history, scope.stored_state, scope.selection)):
        reject("sensitive_scope")
    try:
        async with asyncio.timeout(FILTER_TIMEOUT_SECONDS):
            checked = await checker(scope)
        decision = FilterDecision.model_validate(checked)
    except TimeoutError:
        reject("filter_timeout")
    except ValidationError:
        reject("invalid_filter_result")
    except Exception:
        reject("filter_error")
    if decision.decision == "block":
        reject("filter_blocked")
    if decision.decision == "uncertain":
        reject("filter_uncertain")
    if decision.fields is None:
        reject("missing_technical_fields")

    fields = decision.fields
    if not any(fields.model_dump(exclude_none=True).values()):
        reject("missing_technical_fields")
    goal = TASKS.get(fields.task)
    platform = PLATFORMS.get(fields.platform)
    mail = MAIL_SYSTEMS.get(fields.mail)
    text = f"Нужно {goal}" if goal is not None else "Технические условия"
    if fields.device_count is not None:
        text += f" для {fields.device_count} ПК"
    if fields.license_count is not None:
        text += f", {fields.license_count} лицензий"
    if platform is not None:
        text += f" с {platform}"
    if mail is not None:
        text += f", почтовая система {mail}"
    if fields.deployment is not None:
        text += f", {DEPLOYMENTS[fields.deployment]}"
    return PreparedPrompt(text, goal, platform, mail)
