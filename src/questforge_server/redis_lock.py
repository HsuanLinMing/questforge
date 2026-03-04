from __future__ import annotations

import os
import secrets
import requests
from dataclasses import dataclass
from typing import Optional


@dataclass
class RedisRestLock:
    url: str
    token: str

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def acquire(self, key: str, ttl_seconds: int = 15) -> Optional[str]:
        """
        Returns a lock token if acquired, else None.
        """
        lock_token = secrets.token_hex(16)
        # Upstash REST: SET key value NX EX seconds
        # Endpoint: /set/<key>/<value>?nx=true&ex=15
        try:
            r = requests.get(
                f"{self.url}/set/{key}/{lock_token}",
                params={"nx": "true", "ex": str(ttl_seconds)},
                headers=self._headers(),
                timeout=3,
            )
            r.raise_for_status()
            data = r.json()
            # Upstash returns {"result":"OK"} if set, or {"result":null} if not set
            if data.get("result") == "OK":
                return lock_token
        except Exception as e:
            print(f"[RedisRestLock] acquire failed: {e}")
        return None

    def release(self, key: str, lock_token: str) -> bool:
        """
        Safe release: only delete if value matches our token.
        Use GET then DEL (good enough for MVP). For perfect atomicity, use a Lua script,
        but Upstash REST has /eval support too.
        """
        try:
            r = requests.get(f"{self.url}/get/{key}", headers=self._headers(), timeout=3)
            r.raise_for_status()
            cur = r.json().get("result")
            if cur != lock_token:
                return False
            r2 = requests.get(f"{self.url}/del/{key}", headers=self._headers(), timeout=3)
            r2.raise_for_status()
            return True
        except Exception as e:
            print(f"[RedisRestLock] release failed: {e}")
            return False


def get_redis_lock() -> Optional[RedisRestLock]:
    url = os.getenv("QF_UPSTASH_REDIS_REST_URL", "").strip()
    token = os.getenv("QF_UPSTASH_REDIS_REST_TOKEN", "").strip()
    
    # Trim trailing slash if exists
    if url.endswith("/"):
        url = url[:-1]
        
    if not url or not token:
        return None
    # Normalize: Upstash usually expects https://xxx.upstash.io
    return RedisRestLock(url=url, token=token)
