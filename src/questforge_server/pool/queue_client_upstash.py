from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class UpstashConfig:
    rest_url: str
    rest_token: str


class UpstashRedisRest:
    """
    Minimal Upstash Redis REST client.
    Uses GET requests:
      GET <REST_URL>/<COMMAND>/<arg1>/<arg2>...
    Response JSON:
      {"result": ...}
    """

    def __init__(self, cfg: UpstashConfig):
        self._url = (cfg.rest_url or "").rstrip("/")
        self._token = (cfg.rest_token or "").strip()
        if not self._url or not self._token:
            raise RuntimeError("missing_upstash_config")

    @staticmethod
    def from_env() -> "UpstashRedisRest":
        url = (os.getenv("QF_UPSTASH_REDIS_REST_URL") or os.getenv("UPSTASH_REDIS_REST_URL") or "").strip()
        token = (os.getenv("QF_UPSTASH_REDIS_REST_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN") or "").strip()
        return UpstashRedisRest(UpstashConfig(rest_url=url, rest_token=token))

    def _call(self, path: str) -> Any:
        # ✅ Upstash REST most stable: GET with bearer header, no body
        req = urllib.request.Request(
            url=f"{self._url}/{path.lstrip('/')}",
            method="GET",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return data.get("result")

    def llen(self, key: str) -> int:
        r = self._call(f"LLEN/{urllib.parse.quote(key, safe='')}")
        try:
            return int(r or 0)
        except Exception:
            return 0

    def lpush(self, key: str, value: str) -> int:
        r = self._call(
            f"LPUSH/{urllib.parse.quote(key, safe='')}/{urllib.parse.quote(value, safe='')}"
        )
        try:
            return int(r or 0)
        except Exception:
            return 0

    def rpop(self, key: str) -> Optional[str]:
        r = self._call(f"RPOP/{urllib.parse.quote(key, safe='')}")
        if r is None:
            return None
        return str(r)