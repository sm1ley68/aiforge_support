import json
import logging
from time import monotonic

import httpx

from aisupport_ml.commerce.indexed_chat import INDEXED_SCHEMA
from aisupport_ml.contracts import TemporaryReadError, Usage
from .polza_egress import RESPONSE_FIELDS, SYSTEM, LocalFilter, block, check_transport_request, polza_scope, prepare, record


PROFILE = "qwen-local"
MODEL = "qwen2.5:32b-instruct-q4_K_M"
ENDPOINTS = frozenset(
    f"http://{host}:11434/api/chat" for host in ("127.0.0.1", "localhost", "host.docker.internal", "ollama")
)
logger = logging.getLogger(__name__)


class LocalCatalogModel:
    model = MODEL

    def __init__(self, endpoint: str, checker: LocalFilter | None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.endpoint = endpoint
        self.checker = checker
        self.transport = transport

    async def complete(self, _system, text, schema):
        if self.endpoint not in ENDPOINTS:
            block("invalid_local_endpoint")
        if self.checker is None:
            block("filter_unavailable")
        if schema != INDEXED_SCHEMA or INDEXED_SCHEMA["properties"].keys() != RESPONSE_FIELDS:
            block("schema_not_allowed")

        approved = await prepare(text, self.checker)
        expected = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": approved.text}],
            "format": INDEXED_SCHEMA, "stream": False,
            "options": {"temperature": 0, "num_predict": 384},
        }

        async def validate_request(request: httpx.Request):
            check_transport_request(request, self.endpoint, expected, credentials=False)

        started = monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(35, connect=3), transport=self.transport, trust_env=False,
                event_hooks={"request": [validate_request]},
            ) as client:
                reply = await client.post(self.endpoint, json=expected, follow_redirects=False)
                record("api_response", f"http_{reply.status_code}")
                if not reply.is_success:
                    raise TemporaryReadError("Local model rejected inference")
                payload = reply.json()
                if payload.get("done") is not True or payload.get("done_reason") != "stop":
                    raise ValueError("Incomplete local inference")
                result = approved.validate_answer(json.loads(payload["message"]["content"]))
                counters = (payload.get("prompt_eval_count", 0), payload.get("eval_count", 0))
                if any(type(count) is not int or count < 0 for count in counters):
                    raise ValueError("Invalid local token counts")
        except httpx.RequestError:
            raise TemporaryReadError("Local model is unavailable") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise TemporaryReadError("Invalid local inference response") from None
        scope = polza_scope.get()
        logger.info(
            "ollama_extraction turn_id=%s duration_ms=%d prompt_tokens=%d completion_tokens=%d",
            scope.turn_id if scope else "-", int((monotonic() - started) * 1000), *counters,
        )
        return result, Usage(*counters)
