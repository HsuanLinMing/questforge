# src/questforge_server/pool/pool_manager.py
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
from questforge_server.pool.story_storage_redis import (
    RedisStoryStorage,
    RedisStoryStorageConfig,
)


@dataclass
class AcquireResult:
    source: str
    pkg: StoryNodesPackage
    story_id: Optional[str] = None


class StoryPoolManager:

    def __init__(self, cfg: PoolConfig):
        self._cfg = cfg
        self._sample_repo = SampleStoryRepo(
            SampleRepoConfig(sample_dir=cfg.sample_dir)
        )

        self._redis = UpstashRedisRest.from_env()
        self._jobs_key = "qf:jobs"
        self._ready_key = "qf:ai_ready_queue"  # FIFO: producer RPUSH, consumer LPOP

        import os
        use_redis = os.getenv("QF_POOL_STORAGE", "redis").lower() == "redis"
        if use_redis:
            self._storage = RedisStoryStorage(RedisStoryStorageConfig())
        else:
            self._storage = LocalStoryStorage(
                LocalStoryStorageConfig(root_dir=Path(".qf_cache/pool_ai"))
            )

        self._log(f"storage={type(self._storage).__name__} mode={os.getenv('QF_POOL_STORAGE', 'not set')}")

    # ---------------- helpers ----------------

    def _ready_count(self) -> int:
        return int(self._redis.llen(self._ready_key) or 0)

    def _jobs_count(self) -> int:
        return int(self._redis.llen(self._jobs_key) or 0)

    def _log(self, msg: str, **kv) -> None:
        tail = " ".join([f"{k}={v}" for k, v in kv.items()])
        print(f"[POOL] {msg}" + (f" {tail}" if tail else ""), flush=True)

    def _enqueue_jobs(self, n: int) -> int:
        pushed = 0
        for _ in range(n):
            job = GenerateAiStoryJob.new(seed=None)
            self._redis.lpush(self._jobs_key, job.to_json())
            pushed += 1
        return pushed

    # ---------------- ensure pool ----------------

    def ensure_pool(self) -> None:
        TARGET_READY = 2
        MAX_PENDING = 2

        ready = self._ready_count()
        pending = self._jobs_count()

        if ready >= TARGET_READY:
            self._log("ensure ok", ready=ready, pending=pending)
            return

        if pending >= MAX_PENDING:
            self._log("skip enqueue (pending too high)", ready=ready, pending=pending)
            return

        need = TARGET_READY - ready
        can_push = MAX_PENDING - pending
        enqueue_n = min(need, can_push)

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

    # ---------------- acquire ----------------

    def _try_acquire_ai_ready(
        self,
    ) -> Optional[Tuple[str, StoryNodesPackage]]:
        # ✅ FIFO: LPOP from head of queue – each story consumed by exactly ONE session
        max_tries = 5
        for _ in range(max_tries):
            story_id = self._redis.lpop(self._ready_key)
            if not story_id:
                return None

            try:
                pkg = self._storage.get_story_pkg(story_id)
                # ✅ Consumed: delete from storage immediately (LPOP already removed it from queue)
                try:
                    self._storage.delete_story(story_id)
                except Exception:
                    pass
                self._log("acquire_ai_ok", story_id=story_id[:12])
                return story_id, pkg
            except Exception as e:
                # missing / corrupted → drop and try next
                self._drop_broken_story(str(story_id), reason=repr(e))
                continue
        return None

    def _drop_broken_story(self, story_id: str, reason: str = "") -> None:
        self._log("drop_broken_ai_story", story_id=story_id[:12], reason=reason[:80])
        try:
            self._storage.delete_story(story_id)
        except Exception:
            pass

    def acquire_story(self) -> AcquireResult:
        # ✅ 只 ensure 一次
        try:
            self.ensure_pool()
        except Exception:
            pass

        got = self._try_acquire_ai_ready()
        if got:
            story_id, pkg = got
            return AcquireResult(
                source="ai",
                pkg=pkg,
                story_id=story_id,
            )

        sample_pkg, sample_id = self._sample_repo.acquire_random()
        return AcquireResult(
            source="sample",
            pkg=sample_pkg,
            story_id=sample_id,
        )