# src/questforge_server/pool/story_storage_redis.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

from questforge.contracts.story_nodes_v1 import (
    StoryNodesPackage,
    story_nodes_package_from_dict,
)
from questforge_server.pool.queue_client_upstash import UpstashRedisRest

from pathlib import Path

JsonDict = Dict[str, Any]

@dataclass(frozen=True)
class RedisStoryStorageConfig:
    key_prefix: str = "qf:story:"  # qf:story:<story_id>
    tts_root_dir: Path = Path(".qf_cache/pool_ai/tts")

class RedisStoryStorage:
    def __init__(self, cfg: RedisStoryStorageConfig):
        self._cfg = cfg
        self._redis = UpstashRedisRest.from_env()

    def _key(self, story_id: str) -> str:
        return f"{self._cfg.key_prefix}{story_id}"

    def tts_story_dir(self, story_id: str) -> Path:
        d = self._cfg.tts_root_dir / story_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def story_json_path(self, story_id: str) -> Path:
        # Compatibility polyfill for _prewarm_tts_for_story / worker dedupe
        return Path("/dev/null/not_used")

    def put_story_pkg(self, story_id: str, pkg: StoryNodesPackage, ttl_seconds: int = 604800) -> None:
        """Store story JSON in Redis with TTL (default 7 days)."""
        if hasattr(pkg, "model_dump"):
            data = pkg.model_dump()
        elif hasattr(pkg, "dict"):
            data = pkg.dict()
        elif hasattr(pkg, "to_dict"):
            data = pkg.to_dict()
        else:
            data = json.loads(json.dumps(pkg, default=lambda o: getattr(o, "__dict__", str(o))))
        self._redis.setex(self._key(story_id), json.dumps(data, ensure_ascii=False), ex_seconds=ttl_seconds)

    def get_story_pkg(self, story_id: str) -> StoryNodesPackage:
        s = self._redis.get(self._key(story_id))
        if not s:
            raise FileNotFoundError(f"story not found in redis: {story_id}")
        raw = json.loads(s)
        pkg = story_nodes_package_from_dict(raw)
        if isinstance(pkg, dict):
            if hasattr(StoryNodesPackage, "model_validate"):
                return StoryNodesPackage.model_validate(pkg)  # type: ignore[attr-defined]
            if hasattr(StoryNodesPackage, "parse_obj"):
                return StoryNodesPackage.parse_obj(pkg)  # type: ignore[attr-defined]
            return StoryNodesPackage(**pkg)  # type: ignore[arg-type]
        return pkg

    def delete_story(self, story_id: str) -> None:
        self._redis.delete(self._key(story_id))
