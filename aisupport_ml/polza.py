import json
import os

import httpx

from .contracts import TemporaryReadError, Usage

DEFAULT_BASE_URL = "https://polza.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"


class PolzaIntentModel:
    """Structured ticket extraction through the Polza.ai Chat Completions API."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.endpoint = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
        self.model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.api_key = os.environ.get("LLM_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("Set LLM_API_KEY before configuring Polza.ai")
        if httpx.URL(self.endpoint).scheme != "https":
            raise ValueError("LLM_BASE_URL must use HTTPS")

    async def complete(self, system: str, ticket_text: str, schema: dict) -> tuple[dict, Usage]:
        try:
            response = await self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": ticket_text},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "ticket_intent", "strict": True, "schema": schema},
                    },
                    "stream": False,
                    "temperature": 0,
                    "max_tokens": 256,
                },
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise TemporaryReadError("Polza.ai request failed") from None
        if response.status_code in (408, 429) or response.status_code >= 500:
            raise TemporaryReadError(f"Polza.ai returned HTTP {response.status_code}")
        if not response.is_success:
            raise ValueError(f"Polza.ai rejected inference (HTTP {response.status_code})")

        try:
            body = response.json()
            choice = body["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ValueError("Incomplete inference")
            payload = json.loads(choice["message"]["content"])
            input_tokens = body["usage"]["prompt_tokens"]
            output_tokens = body["usage"]["completion_tokens"]
        except (IndexError, KeyError, TypeError, ValueError):
            raise ValueError("Invalid or incomplete Polza.ai response") from None
        if any(type(count) is not int or count < 0 for count in (input_tokens, output_tokens)):
            raise ValueError("Invalid Polza.ai token counts")
        return payload, Usage(input_tokens, output_tokens)
