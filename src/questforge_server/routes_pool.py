# src/questforge_server/routes_pool.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from fastapi import APIRouter

from questforge_server.pool.queue_client_upstash import UpstashRedisRest

router = APIRouter(prefix="/v1/pool", tags=["pool"])


@router.get("/status")
def pool_status() -> Dict[str, Any]:
    redis = None
    upstash: Dict[str, Any] = {
        "available": False,
        "summary": UpstashRedisRest.env_summary(),
        "jobs_len": 0,
        "ready_ai_len": 0,
        "dead_len": 0,
    }
    try:
        redis = UpstashRedisRest.from_env()
        upstash["available"] = True
    except Exception as e:
        upstash["error"] = str(e)

    jobs_key = "qf:jobs"
    ready_key = "qf:ai_ready_queue"
    dead_key = "qf:dead"

    root = Path(".qf_cache/pool_ai")
    stories_dir = root / "stories"
    tts_dir = root / "tts"

    def _count_files(p: Path, suffix: str) -> int:
        try:
            if not p.exists():
                return 0
            return sum(1 for x in p.rglob(f"*{suffix}") if x.is_file())
        except Exception:
            return 0

    def _llen_safe(key: str) -> int:
        if redis is None:
            return 0
        try:
            return redis.llen(key)
        except Exception as e:
            upstash["available"] = False
            upstash["error"] = str(e)
            return 0

    return {
        "ok": True,
        "upstash": {
            **upstash,
            "jobs_len": _llen_safe(jobs_key),
            "ready_ai_len": _llen_safe(ready_key),
            "dead_len": _llen_safe(dead_key),
        },
        "local_storage": {
            "root": str(root.resolve()),
            "stories_json": _count_files(stories_dir, ".json"),
            "tts_wav": _count_files(tts_dir, ".wav"),
        },
    }
