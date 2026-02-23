# src/questforge_server/pool/sample_repo.py
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from questforge.contracts.story_nodes_v1 import (
    StoryNodesPackage,
    story_nodes_package_from_dict,
)
from questforge.contracts.story_nodes_validator_v1 import (
    validate_story_nodes_v1,
    StoryNodesValidationError,
)

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class SampleRepoConfig:
    # folder: src/questforge/content/sample_pool_json
    sample_dir: Path


def _coerce_to_pkg(raw: Any) -> StoryNodesPackage:
    """
    兼容你目前專案中 story_nodes_package_from_dict 可能回 dict 的情況。
    最終保證回傳 StoryNodesPackage（有 pkg.meta）。
    """
    pkg = story_nodes_package_from_dict(raw)

    # ✅ 有些版本會回 dict（你現在就是這種），所以要再轉一次
    if isinstance(pkg, dict):
        # pydantic v2
        if hasattr(StoryNodesPackage, "model_validate"):
            return StoryNodesPackage.model_validate(pkg)  # type: ignore[attr-defined]
        # pydantic v1
        if hasattr(StoryNodesPackage, "parse_obj"):
            return StoryNodesPackage.parse_obj(pkg)  # type: ignore[attr-defined]
        # dataclass / fallback
        return StoryNodesPackage(**pkg)  # type: ignore[arg-type]

    # 已經是 StoryNodesPackage
    return pkg


class SampleStoryRepo:
    def __init__(self, cfg: SampleRepoConfig):
        self._cfg = cfg
        self._paths: List[Path] = []
        self._refresh_paths()

    def _refresh_paths(self) -> None:
        d = self._cfg.sample_dir
        if not d.exists() or not d.is_dir():
            self._paths = []
            return
        self._paths = sorted(d.glob("*.storynodes.json"))

    def count(self) -> int:
        return len(self._paths)

    def acquire_random(self) -> StoryNodesPackage:
        """
        Pick a random sample storynodes json -> StoryNodesPackage -> validate.
        Raises RuntimeError if no valid sample exists.
        """
        if not self._paths:
            self._refresh_paths()
        if not self._paths:
            raise RuntimeError(f"No sample stories found in {self._cfg.sample_dir}")

        candidates = self._paths[:]
        random.shuffle(candidates)

        last_err: Optional[Exception] = None
        for p in candidates:
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                pkg = _coerce_to_pkg(raw)

                # ✅ 這裡要丟「StoryNodesPackage」不是 dict
                validate_story_nodes_v1(pkg)

                return pkg
            except (OSError, json.JSONDecodeError, StoryNodesValidationError) as e:
                last_err = e
                continue

        raise RuntimeError(f"All sample stories are invalid. last_err={last_err!r}")