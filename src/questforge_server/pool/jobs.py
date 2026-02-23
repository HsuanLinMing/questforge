from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class GenerateAiStoryJob:
    kind: str  # "gen_ai_story_v1"
    story_id: str
    seed: Optional[int] = None

    @staticmethod
    def new(seed: Optional[int] = None) -> "GenerateAiStoryJob":
        return GenerateAiStoryJob(kind="gen_ai_story_v1", story_id=uuid.uuid4().hex, seed=seed)

    def to_json(self) -> str:
        return json.dumps({"kind": self.kind, "story_id": self.story_id, "seed": self.seed}, ensure_ascii=False)

    @staticmethod
    def from_json(s: str) -> "GenerateAiStoryJob":
        d = json.loads(s)
        return GenerateAiStoryJob(
            kind=str(d.get("kind") or ""),
            story_id=str(d.get("story_id") or ""),
            seed=d.get("seed"),
        )