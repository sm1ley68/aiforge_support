import json

import httpx

from .contracts import TemporaryReadError, Usage


class OllamaIntentModel:
    """Structured inference via an Ollama server configured by the worker."""

    def __init__(self, client: httpx.AsyncClient, model: str, *, storefront: bool = False):
        self.client = client
        self.model = model
        self.storefront = storefront

    async def complete(self, system: str, ticket_text: str, schema: dict) -> tuple[dict, Usage]:
        try:
            response = await self.client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": ticket_text},
                    ],
                    "format": schema,
                    "stream": False,
                    "options": {
                        "temperature": 0, **({"num_ctx": 2048, "num_predict": 384, "seed": 42}
                                             if self.storefront else {}),
                    },
                    **({"think": False} if self.storefront else {}),
                },
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise TemporaryReadError from None
        if response.status_code in (408, 429) or response.status_code >= 500:
            raise TemporaryReadError
        if not response.is_success:
            raise ValueError("Ollama rejected structured inference")
        try:
            body = response.json()
            if self.storefront and (body.get("done") is not True or body.get("done_reason") != "stop"):
                raise ValueError("Incomplete Ollama response")
            payload = json.loads(body["message"]["content"])
            input_tokens = body["prompt_eval_count"]
            output_tokens = body["eval_count"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("Invalid Ollama response") from None
        if any(type(count) is not int or count < 0 for count in (input_tokens, output_tokens)):
            raise ValueError("Invalid Ollama token counts")
        return payload, Usage(input_tokens, output_tokens)
