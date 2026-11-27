"""Run the guarded storefront extraction contract on a local Ollama instance."""

import logging
from importlib.util import find_spec
from time import monotonic

import httpx

from aisupport_ml.commerce.indexed_chat import INDEXED_SCHEMA
from aisupport_ml.contracts import TemporaryReadError
from aisupport_ml.ollama import OllamaIntentModel

from .polza_egress import SYSTEM, LocalFilter, _native_filter, polza_scope, prepare


MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_URL = "http://127.0.0.1:11434"
LOCAL_TIMEOUT_SECONDS = 30
logger = logging.getLogger(__name__)


def reject_local(category: str):
    scope = polza_scope.get()
    logger.info("local_guard turn_id=%s category=%s", scope.turn_id if scope else "-", category)
    raise TemporaryReadError("Local extraction was not accepted")


class LocalCatalogModel:
    model = MODEL

    def __init__(
        self, url: str, *, checker: LocalFilter | None = None, transport: httpx.AsyncBaseTransport | None = None,
    ):
        parsed = httpx.URL(url)
        if (parsed.scheme != "http" or parsed.host not in {"127.0.0.1", "::1", "ollama"} or parsed.port != 11434
                or parsed.path not in {"", "/"} or parsed.userinfo or parsed.query or parsed.fragment):
            raise ValueError("Ollama must use loopback or the private Compose service on port 11434")
        self.url = parsed
        self.checker = checker or (_native_filter if find_spec("natasha") is not None else None)
        self.transport = transport

    async def complete(self, _system: str, text: str, schema: dict):
        if self.checker is None or schema != INDEXED_SCHEMA:
            reject_local("filter_or_schema_unavailable")
        approved = await prepare(text, self.checker, reject=reject_local)
        scope = polza_scope.get()
        started = monotonic()
        status = "unavailable"
        usage = None
        try:
            async with httpx.AsyncClient(
                base_url=self.url, timeout=LOCAL_TIMEOUT_SECONDS - 1, trust_env=False, transport=self.transport,
            ) as client:
                result, usage = await OllamaIntentModel(client, MODEL, storefront=True).complete(
                    SYSTEM, approved.text, schema,
                )
            result = approved.validate_answer(result, reject=reject_local)
            status = "ok"
            return result, usage
        except (TemporaryReadError, ValueError) as error:
            status = type(error).__name__
            raise
        finally:
            logger.info(
                "ollama_extraction turn_id=%s status=%s duration_ms=%d prompt_tokens=%s completion_tokens=%s",
                scope.turn_id if scope else "-", status, round(1000 * (monotonic() - started)),
                usage.input_tokens if usage else None, usage.output_tokens if usage else None,
            )
