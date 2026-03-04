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

    - For small commands, we use GET:
        GET <REST_URL>/<COMMAND>/<arg1>/<arg2>...
      Response JSON: {"result": ...}

    - For large payloads (e.g. SET big JSON value), we use POST with JSON body:
        POST <REST_URL>  body: ["SET", "key", "value"]
      Response JSON: {"result": ...}

    This avoids URL length limits when storing big StoryNodes JSON.
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

    # -------------------------
    # Low-level calls
    # -------------------------

    def _call_get(self, path: str) -> Any:
        # ✅ Upstash REST: GET with bearer header, no body
        req = urllib.request.Request(
            url=f"{self._url}/{path.lstrip('/')}",
            method="GET",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return data.get("result")

    def _call_post_cmd(self, cmd: list[str]) -> Any:
        # ✅ Upstash REST: POST body is a JSON array, e.g. ["SET","k","v"]
        payload = json.dumps(cmd, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=f"{self._url}",
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            data=payload,
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return data.get("result")

    @staticmethod
    def _q(s: str) -> str:
        return urllib.parse.quote(s, safe="")

    # -------------------------
    # List ops (GET)
    # -------------------------

    def llen(self, key: str) -> int:
        r = self._call_get(f"LLEN/{self._q(key)}")
        try:
            return int(r or 0)
        except Exception:
            return 0

    def lpush(self, key: str, value: str) -> int:
        r = self._call_get(f"LPUSH/{self._q(key)}/{self._q(value)}")
        try:
            return int(r or 0)
        except Exception:
            return 0

    def rpop(self, key: str) -> Optional[str]:
        r = self._call_get(f"RPOP/{self._q(key)}")
        if r is None:
            return None
        return str(r)

    # -------------------------
    # KV ops
    # -------------------------

    def get(self, key: str) -> Optional[str]:
        r = self._call_get(f"GET/{self._q(key)}")
        if r is None:
            return None
        # Upstash returns raw string or JSON-encoded string depending on stored value
        return str(r)

    def set(self, key: str, value: str) -> bool:
        # ✅ use POST to avoid URL length limits
        r = self._call_post_cmd(["SET", key, value])
        # Upstash returns "OK" on success
        return str(r).upper() == "OK"

    def delete(self, key: str) -> int:
        r = self._call_get(f"DEL/{self._q(key)}")
        try:
            return int(r or 0)
        except Exception:
            return 0