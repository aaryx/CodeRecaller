import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

from coderecall.domain.errors import ProviderError
from coderecall.domain.validation import validate_url


@dataclass
class ProblemMetadata:
    title: str
    platform: str = "custom"
    external_id: str = ""
    slug: str = ""
    url: str = ""
    difficulty: str = "unknown"
    topics: list[str] = field(default_factory=list)


class ProblemProvider(Protocol):
    def fetch(self, url: str) -> ProblemMetadata: ...


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class LeetCodeProvider:
    def fetch(self, url: str) -> ProblemMetadata:
        validate_url(url, leetcode=True)
        slug = urlsplit(url).path.split("/")[2]
        body = json.dumps(
            {
                "query": "query($slug:String!){question(titleSlug:$slug){questionFrontendId title titleSlug difficulty topicTags{name slug}}}",
                "variables": {"slug": slug},
            }
        ).encode()
        request = urllib.request.Request(
            "https://leetcode.com/graphql",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "CodeRecall"},
        )
        opener = urllib.request.build_opener(NoRedirect())
        for attempt in range(3):
            try:
                with opener.open(request, timeout=10) as response:  # noqa: S310 -- fixed HTTPS endpoint
                    raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ProviderError("Metadata response too large; enter metadata manually")
                data = json.loads(raw)["data"]["question"]
                if not isinstance(data, dict) or not all(
                    isinstance(data.get(k), str)
                    for k in ["title", "titleSlug", "questionFrontendId", "difficulty"]
                ):
                    raise ValueError
                topics = [item["slug"] for item in data.get("topicTags", [])]
                if not all(isinstance(topic, str) for topic in topics):
                    raise ValueError
                return ProblemMetadata(
                    data["title"],
                    "leetcode",
                    data["questionFrontendId"],
                    data["titleSlug"],
                    url,
                    data["difficulty"].lower(),
                    topics,
                )
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403, 429}:
                    raise ProviderError(
                        "LeetCode denied/rate-limited metadata access; enter metadata manually"
                    ) from exc
                if exc.code < 500 or attempt == 2:
                    raise ProviderError(
                        "LeetCode metadata unavailable; enter metadata manually"
                    ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise ProviderError(
                        "Metadata request timed out/unavailable; enter metadata manually"
                    ) from exc
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderError("Invalid metadata response; enter metadata manually") from exc
            time.sleep(0.5 * 2**attempt)
        raise ProviderError("Metadata unavailable")
