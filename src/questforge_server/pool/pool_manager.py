# src/questforge_server/pool/pool_manager.py
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Optional, Tuple

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

        self._redis: Optional[UpstashRedisRest] = None
        self._redis_error: str = ""
        self._jobs_key = "qf:jobs"
        self._ready_key = "qf:ai_ready_queue"  # FIFO: producer RPUSH, consumer LPOP

        try:
            self._redis = UpstashRedisRest.from_env()
        except Exception as e:
            self._redis_error = str(e)

        use_redis = os.getenv("QF_POOL_STORAGE", "redis").lower() == "redis"
        self._storage = self._make_local_storage()
        if use_redis and self._redis is not None:
            try:
                self._storage = RedisStoryStorage(RedisStoryStorageConfig())
            except Exception as e:
                self._redis_error = f"redis_storage_init_failed: {e}"
                self._storage = self._make_local_storage()
                self._redis = None
        elif use_redis and self._redis is None:
            self._log("redis unavailable -> sample/local fallback", err=self._redis_error[:200])

        self._log(f"storage={type(self._storage).__name__} mode={os.getenv('QF_POOL_STORAGE', 'not set')}")
        if self._redis is not None:
            self._log("redis configured", host=self._redis.host, url=self._redis.base_url)

    def _make_local_storage(self) -> LocalStoryStorage:
        return LocalStoryStorage(
            LocalStoryStorageConfig(root_dir=Path(".qf_cache/pool_ai"))
        )

    def _disable_redis(self, reason: str) -> None:
        self._redis_error = reason
        if self._redis is not None:
            self._log("redis disabled", reason=reason[:240], host=self._redis.host)
        else:
            self._log("redis disabled", reason=reason[:240])
        self._redis = None
        if isinstance(self._storage, RedisStoryStorage):
            self._storage = self._make_local_storage()

    def redis_enabled(self) -> bool:
        return self._redis is not None

    def redis_status(self) -> dict[str, Any]:
        return {
            "enabled": self._redis is not None,
            "host": self._redis.host if self._redis is not None else "<disabled>",
            "url": self._redis.base_url if self._redis is not None else "",
            "error": self._redis_error,
        }

    def _redis_hgetall(self, key: str) -> dict:
        if self._redis is None:
            return {}
        try:
            return self._redis.hgetall(key)
        except Exception as e:
            self._disable_redis(f"redis hgetall failed key={key!r} err={e}")
            return {}

    def tts_ready_map(self, view_fp: str) -> dict:
        return self._redis_hgetall(f"qf:tts_ready:{view_fp}")

    # ---------------- helpers ----------------

    def _ready_count(self) -> int:
        if self._redis is None:
            return 0
        try:
            return int(self._redis.llen(self._ready_key) or 0)
        except Exception as e:
            self._disable_redis(f"redis ready_count failed key={self._ready_key!r} err={e}")
            return 0

    def _jobs_count(self) -> int:
        if self._redis is None:
            return 0
        try:
            return int(self._redis.llen(self._jobs_key) or 0)
        except Exception as e:
            self._disable_redis(f"redis jobs_count failed key={self._jobs_key!r} err={e}")
            return 0

    def _log(self, msg: str, **kv) -> None:
        tail = " ".join([f"{k}={v}" for k, v in kv.items()])
        print(f"[POOL] {msg}" + (f" {tail}" if tail else ""), flush=True)

    def _enqueue_jobs(self, n: int) -> int:
        if self._redis is None:
            return 0
        pushed = 0
        for _ in range(n):
            job = GenerateAiStoryJob.new(seed=None)
            try:
                self._redis.lpush(self._jobs_key, job.to_json())
            except Exception as e:
                self._disable_redis(f"redis enqueue failed key={self._jobs_key!r} err={e}")
                break
            pushed += 1
        return pushed

    # ---------------- ensure pool ----------------

    def ensure_pool(self) -> None:
        if self._redis is None:
            self._log("ensure skip (redis unavailable)", err=self._redis_error[:200] or "redis_disabled")
            return

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
        if self._redis is None:
            return None

        # ✅ FIFO: LPOP from head of queue – each story consumed by exactly ONE session
        max_tries = 5
        for _ in range(max_tries):
            try:
                story_id = self._redis.lpop(self._ready_key)
            except Exception as e:
                self._disable_redis(f"redis acquire failed key={self._ready_key!r} err={e}")
                return None
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
            except FileNotFoundError as e:
                # missing / corrupted → drop and try next
                self._drop_broken_story(str(story_id), reason=repr(e))
                continue
            except Exception as e:
                self._disable_redis(
                    f"redis-backed story fetch failed story_id={story_id[:12]!r} err={e}"
                )
                return None
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

        if self._redis is None and self._redis_error:
            self._log("sample fallback", reason=self._redis_error[:240])
        sample_pkg, sample_id = self._sample_repo.acquire_random()
        return AcquireResult(
            source="sample",
            pkg=sample_pkg,
            story_id=sample_id,
        )
