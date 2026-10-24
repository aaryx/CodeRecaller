"""Optional fixed-endpoint OpenAI adapter. Credentials are never persisted."""

import json
import os
import time
import urllib.error
import urllib.request

from coderecall.domain.errors import AuthenticationError, ProviderError
from coderecall.integrations.problems import NoRedirect


class OpenAIProvider:
    def __init__(self, model: str):
        self.model = model

    def generate(self, instruction: str, untrusted_content: str) -> str:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise AuthenticationError(
                "Set OPENAI_API_KEY in the process environment; never project configuration"
            )
        payload = json.dumps(
            {
                "model": self.model,
                "store": False,
                "max_completion_tokens": 2048,
                "messages": [
                    {"role": "developer", "content": instruction},
                    {"role": "user", "content": untrusted_content},
                ],
            }
        ).encode()
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        opener = urllib.request.build_opener(NoRedirect())
        for attempt in range(3):
            try:
                with opener.open(request, timeout=30) as response:  # noqa: S310 -- fixed HTTPS endpoint, no redirects
                    raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ProviderError("AI response exceeds size limit")
                data = json.loads(raw)
                choice = data["choices"][0]
                message = choice["message"]
                if choice.get("finish_reason") != "stop" or message.get("tool_calls"):
                    raise ProviderError(
                        "AI returned incomplete output or a tool request; discarded"
                    )
                content = message.get("content")
                if not isinstance(content, str) or not content.strip() or len(content) > 100000:
                    raise ProviderError("Invalid AI response text")
                return content
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403}:
                    raise AuthenticationError("OpenAI authentication/permission denied") from None
                if exc.code == 429:
                    raise ProviderError("OpenAI rate limit reached; retry later") from None
                if exc.code < 500 or attempt == 2:
                    raise ProviderError(
                        f"OpenAI request failed (HTTP {exc.code}); response details suppressed"
                    ) from None
            except (urllib.error.URLError, TimeoutError):
                # Do not retry ambiguous POST timeouts, which may already have incurred billing.
                raise ProviderError(
                    "OpenAI request timed out/unavailable; not retried to avoid duplicate billing"
                ) from None
            except (ValueError, KeyError, TypeError, IndexError):
                raise ProviderError("Malformed OpenAI response") from None
            time.sleep(0.5 * 2**attempt)
        raise ProviderError("OpenAI unavailable")
