from __future__ import annotations

import json
import os
import urllib.parse
import urllib.error
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
        parsed = urllib.parse.urlparse(self._url)
        issues: list[str] = []
        if parsed.scheme not in ("http", "https"):
            issues.append("invalid_scheme")
        if not parsed.netloc:
            issues.append("missing_host")
        if issues:
            raise RuntimeError(
                f"invalid_upstash_config url={self._url!r} "
                f"scheme={parsed.scheme or '<empty>'} "
                f"host={parsed.netloc or '<empty>'} issues={','.join(issues)}"
            )

    @property
    def base_url(self) -> str:
        return self._url

    @property
    def host(self) -> str:
        return urllib.parse.urlparse(self._url).netloc or "<empty>"

    @staticmethod
    def from_env() -> "UpstashRedisRest":
        url = (os.getenv("QF_UPSTASH_REDIS_REST_URL") or os.getenv("UPSTASH_REDIS_REST_URL") or "").strip()
        token = (os.getenv("QF_UPSTASH_REDIS_REST_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN") or "").strip()
        try:
            return UpstashRedisRest(UpstashConfig(rest_url=url, rest_token=token))
        except Exception as e:
            raise RuntimeError(
                "upstash_env_error "
                f"url={url!r} token_set={bool(token)} err={e}"
            ) from e

    @staticmethod
    def env_summary() -> str:
        url = (os.getenv("QF_UPSTASH_REDIS_REST_URL") or os.getenv("UPSTASH_REDIS_REST_URL") or "").strip()
        parsed = urllib.parse.urlparse(url) if url else None
        issues: list[str] = []
        if not url:
            issues.append("missing")
        else:
            if parsed and parsed.scheme not in ("http", "https"):
                issues.append("invalid_scheme")
            if parsed and not parsed.netloc:
                issues.append("missing_host")
        status = "ok" if not issues else ",".join(issues)
        return (
            f"url={url!r} "
            f"host={(parsed.netloc if parsed else '') or '<empty>'} "
            f"token_set={bool((os.getenv('QF_UPSTASH_REDIS_REST_TOKEN') or os.getenv('UPSTASH_REDIS_REST_TOKEN') or '').strip())} "
            f"status={status}"
        )

    def startup_check(self) -> dict:
        try:
            jobs_len = self.llen("qf:jobs")
            return {
                "ok": True,
                "host": self.host,
                "url": self.base_url,
                "jobs_len": jobs_len,
            }
        except Exception as e:
            return {
                "ok": False,
                "host": self.host,
                "url": self.base_url,
                "error": str(e),
            }

    # -------------------------
    # Low-level calls
    # -------------------------

    def _call_get(self, path: str) -> Any:
        url = f"{self._url}/{path.lstrip('/')}"
        req = urllib.request.Request(
            url=url,
            method="GET",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                return data.get("result")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            host = urllib.parse.urlparse(url).netloc or "<empty>"
            print(
                "[Upstash] GET HTTPError",
                {"host": host, "url": url, "status": e.code, "body": body[:200]},
                flush=True,
            )
            raise RuntimeError(
                f"Upstash GET HTTPError status={e.code} host={host!r} "
                f"url={url!r} body={body[:200]!r}"
            ) from e
        except urllib.error.URLError as e:
            host = urllib.parse.urlparse(url).netloc or "<empty>"
            print(
                "[Upstash] GET URLError",
                {"host": host, "url": url, "err": repr(e)},
                flush=True,
            )
            raise RuntimeError(
                f"Upstash GET URLError host={host!r} url={url!r} err={e!r}"
            ) from e

    def _call_post_cmd(self, cmd: list) -> Any:
        # ✅ Upstash REST: POST body is a JSON array, e.g. ["SET","k","v"]
        payload = json.dumps(cmd, ensure_ascii=False).encode("utf-8")
        url = f"{self._url}"
        req = urllib.request.Request(
            url=url,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            data=payload,
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                return data.get("result")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            host = urllib.parse.urlparse(url).netloc or "<empty>"
            print(
                "[Upstash] POST HTTPError",
                {
                    "host": host,
                    "url": url,
                    "status": e.code,
                    "cmd": cmd[:3],
                    "body": body[:200],
                },
                flush=True,
            )
            raise RuntimeError(
                f"Upstash POST HTTPError status={e.code} host={host!r} "
                f"url={url!r} cmd={cmd[:3]!r} body={body[:200]!r}"
            ) from e
        except urllib.error.URLError as e:
            host = urllib.parse.urlparse(url).netloc or "<empty>"
            print(
                "[Upstash] POST URLError",
                {"host": host, "url": url, "cmd": cmd[:3], "err": repr(e)},
                flush=True,
            )
            raise RuntimeError(
                f"Upstash POST URLError host={host!r} url={url!r} "
                f"cmd={cmd[:3]!r} err={e!r}"
            ) from e

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
