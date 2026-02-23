from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from questforge.contracts.story_nodes_v1 import StoryNodesPackage, story_nodes_package_from_dict

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class LocalStoryStorageConfig:
    root_dir: Path  # e.g. .qf_cache/pool_ai


class LocalStoryStorage:
    """
    Stores AI-generated story nodes JSON + pooled TTS files under root_dir.
    """
    def __init__(self, cfg: LocalStoryStorageConfig):
        self._root = cfg.root_dir.resolve()
        self._stories = self._root / "stories"
        self._tts = self._root / "tts"
        self._stories.mkdir(parents=True, exist_ok=True)
        self._tts.mkdir(parents=True, exist_ok=True)

    def story_json_path(self, story_id: str) -> Path:
        return self._stories / f"{story_id}.storynodes.json"

    def tts_story_dir(self, story_id: str) -> Path:
        d = self._tts / story_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def put_story_pkg(self, story_id: str, pkg: StoryNodesPackage) -> Path:
        p = self.story_json_path(story_id)
        # pydantic v2: model_dump; v1: dict; dataclass: __dict__ fallback
        if hasattr(pkg, "model_dump"):
            data = pkg.model_dump()
        elif hasattr(pkg, "dict"):
            data = pkg.dict()
        elif hasattr(pkg, "to_dict"):
            data = pkg.to_dict()
        else:
            data = json.loads(json.dumps(pkg, default=lambda o: getattr(o, "__dict__", str(o))))
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def get_story_pkg(self, story_id: str) -> StoryNodesPackage:
        p = self.story_json_path(story_id)
        raw = json.loads(p.read_text(encoding="utf-8"))
        pkg = story_nodes_package_from_dict(raw)
        # 若你專案這個函式回 dict，就再轉一次（跟 sample_repo 同邏輯）
        if isinstance(pkg, dict):
            if hasattr(StoryNodesPackage, "model_validate"):
                return StoryNodesPackage.model_validate(pkg)  # type: ignore[attr-defined]
            if hasattr(StoryNodesPackage, "parse_obj"):
                return StoryNodesPackage.parse_obj(pkg)  # type: ignore[attr-defined]
            return StoryNodesPackage(**pkg)  # type: ignore[arg-type]
        return pkg