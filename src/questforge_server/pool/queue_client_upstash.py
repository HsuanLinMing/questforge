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
        req = urllib.request.Request(
            url=f"{self._url}/{path.lstrip('/')}",
            method="GET",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return data.get("result")

    def _call_post_cmd(self, cmd: list) -> Any:
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
    # List ops
    # -------------------------

    def llen(self, key: str) -> int:
        r = self._call_get(f"LLEN/{self._q(key)}")
        try:
            return int(r or 0)
        except Exception:
            return 0

    def lpush(self, key: str, value: str) -> int:
        """Push to HEAD of list."""
        r = self._call_get(f"LPUSH/{self._q(key)}/{self._q(value)}")
        try:
            return int(r or 0)
        except Exception:
            return 0

    def rpush(self, key: str, value: str) -> int:
        """Push to TAIL of list (producer side of FIFO queue)."""
        r = self._call_get(f"RPUSH/{self._q(key)}/{self._q(value)}")
        try:
            return int(r or 0)
        except Exception:
            return 0

    def rpop(self, key: str) -> Optional[str]:
        """Pop from TAIL of list."""
        r = self._call_get(f"RPOP/{self._q(key)}")
        if r is None:
            return None
        return str(r)

    def lpop(self, key: str) -> Optional[str]:
        """Pop from HEAD of list (consumer side of FIFO queue; RPUSH+LPOP = FIFO)."""
        r = self._call_get(f"LPOP/{self._q(key)}")
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
        return str(r)

    def set(self, key: str, value: str) -> bool:
        """SET without TTL. Always use POST to avoid URL length limits."""
        r = self._call_post_cmd(["SET", key, value])
        return str(r).upper() == "OK"

    def setex(self, key: str, value: str, ex_seconds: int) -> bool:
        """SET with EX TTL. Always POST for large values."""
        r = self._call_post_cmd(["SET", key, value, "EX", str(ex_seconds)])
        return str(r).upper() == "OK"

    def delete(self, key: str) -> int:
        r = self._call_get(f"DEL/{self._q(key)}")
        try:
            return int(r or 0)
        except Exception:
            return 0

    def expire(self, key: str, seconds: int) -> int:
        """Set TTL on existing key. Returns 1 on success, 0 if key doesn't exist."""
        r = self._call_get(f"EXPIRE/{self._q(key)}/{seconds}")
        try:
            return int(r or 0)
        except Exception:
            return 0

    # -------------------------
    # Hash ops (used for TTS ready map: qf:tts_ready:<view_fp>)
    # -------------------------

    def hset(self, key: str, field: str, value: str) -> int:
        """HSET key field value — always POST to handle large values."""
        r = self._call_post_cmd(["HSET", key, field, value])
        try:
            return int(r or 0)
        except Exception:
            return 0

    def hget(self, key: str, field: str) -> Optional[str]:
        r = self._call_get(f"HGET/{self._q(key)}/{self._q(field)}")
        if r is None:
            return None
        return str(r)

    def hgetall(self, key: str) -> dict:
        """HGETALL — returns {field: value, ...}. Upstash returns flat list."""
        r = self._call_get(f"HGETALL/{self._q(key)}")
        if not isinstance(r, list):
            return {}
        it = iter(r)
        return {k: v for k, v in zip(it, it)}