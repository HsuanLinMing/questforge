# src/questforge_server/routes_pool.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from fastapi import APIRouter

from questforge_server.pool.queue_client_upstash import UpstashRedisRest

router = APIRouter(prefix="/v1/pool", tags=["pool"])


@router.get("/status")
def pool_status() -> Dict[str, Any]:
    redis = UpstashRedisRest.from_env()

    jobs_key = "qf:jobs"
    ready_key = "qf:ready_ai"
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

    return {
        "ok": True,
        "upstash": {
            "jobs_len": redis.llen(jobs_key),
            "ready_ai_len": redis.llen(ready_key),
            "dead_len": redis.llen(dead_key),
        },
        "local_storage": {
            "root": str(root.resolve()),
            "stories_json": _count_files(stories_dir, ".json"),
            "tts_wav": _count_files(tts_dir, ".wav"),
        },
    }