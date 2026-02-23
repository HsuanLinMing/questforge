from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from questforge.contracts.story_nodes_v1 import StoryNodesPackage

from questforge_server.pool.pool_config import PoolConfig
from questforge_server.pool.sample_repo import SampleRepoConfig, SampleStoryRepo
from questforge_server.pool.queue_client_upstash import UpstashRedisRest
from questforge_server.pool.jobs import GenerateAiStoryJob
from questforge_server.pool.story_storage_local import (
    LocalStoryStorage,
    LocalStoryStorageConfig,
)


@dataclass
class AcquireResult:
    source: str  # "ai" or "sample"
    pkg: StoryNodesPackage
    story_id: Optional[str] = None


class StoryPoolManager:
    """
    Upstash-backed AI story pool
    """

    def __init__(self, cfg: PoolConfig):
        self._cfg = cfg
        self._sample_repo = SampleStoryRepo(
            SampleRepoConfig(sample_dir=cfg.sample_dir)
        )

        self._redis = UpstashRedisRest.from_env()
        self._jobs_key = "qf:jobs"
        self._ready_key = "qf:ready_ai"

        self._storage = LocalStoryStorage(
            LocalStoryStorageConfig(root_dir=Path(".qf_cache/pool_ai"))
        )

    # --------------------------------------------------
    # small helpers
    # --------------------------------------------------

    def _ready_count(self) -> int:
        return int(self._redis.llen(self._ready_key) or 0)

    def _jobs_count(self) -> int:
        return int(self._redis.llen(self._jobs_key) or 0)

    def _log(self, msg: str, **kv) -> None:
        try:
            tail = " ".join([f"{k}={v}" for k, v in kv.items()])
            print(f"[POOL] {msg}" + (f" {tail}" if tail else ""), flush=True)
        except Exception:
            pass

    # --------------------------------------------------
    # pool sizing
    # --------------------------------------------------

    def _max_enqueue_once(self) -> int:
        import os
        raw = (os.getenv("QF_POOL_MAX_ENQUEUE_ONCE") or "").strip()
        if raw:
            try:
                return max(1, min(20, int(raw)))
            except Exception:
                pass
        return 3

    def _max_pending_jobs(self) -> int:
        import os
        raw = (os.getenv("QF_POOL_MAX_PENDING_JOBS") or "").strip()
        if raw:
            try:
                return max(0, min(100, int(raw)))
            except Exception:
                pass
        return 6

    def _enqueue_jobs(self, n: int) -> int:
        if n <= 0:
            return 0
        pushed = 0
        for _ in range(n):
            job = GenerateAiStoryJob.new(seed=None)
            self._redis.lpush(self._jobs_key, job.to_json())
            pushed += 1
        return pushed

    # --------------------------------------------------
    # ensure pool
    # --------------------------------------------------

    def ensure_pool(self) -> None:
        min_ready = int(getattr(self._cfg, "min_ready", 2) or 2)
        ready = self._ready_count()
        pending = self._jobs_count()

        need = max(0, min_ready - ready)

        if need <= 0:
            self._log("ensure ok", ready=ready, pending=pending)
            return

        max_pending = self._max_pending_jobs()
        if pending >= max_pending:
            self._log(
                "skip enqueue (pending too high)",
                ready=ready,
                pending=pending,
                max_pending=max_pending,
            )
            return

        cap = self._max_enqueue_once()
        enqueue_n = min(need, cap, max_pending - pending)

        if enqueue_n <= 0:
            return

        pushed = self._enqueue_jobs(enqueue_n)

        self._log(
            "enqueue",
            ready=ready,
            pending=pending,
            need=need,
            pushed=pushed,
        )

    # --------------------------------------------------
    # acquire
    # --------------------------------------------------

    def _try_acquire_ai_ready(
        self,
    ) -> Optional[Tuple[str, StoryNodesPackage]]:

        story_id = self._redis.rpop(self._ready_key)
        if not story_id:
            return None

        try:
            pkg = self._storage.get_story_pkg(story_id)
            return story_id, pkg
        except Exception as e:
            self._log(
                "drop broken story",
                story_id=str(story_id)[:12],
                err=repr(e),
            )
            return None

    def acquire_story(self) -> AcquireResult:
        try:
            self.ensure_pool()
        except Exception:
            pass

        got = self._try_acquire_ai_ready()
        if got is not None:
            story_id, pkg = got
            try:
                self.ensure_pool()
            except Exception:
                pass
            return AcquireResult(
                source="ai",
                pkg=pkg,
                story_id=story_id,
            )

        sample_pkg = self._sample_repo.acquire_random()
        return AcquireResult(
            source="sample",
            pkg=sample_pkg,
            story_id=None,
        )