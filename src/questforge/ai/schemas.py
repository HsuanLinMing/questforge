from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


# -------------------------
# Story (case) generation
# -------------------------

@dataclass
class StoryCharacter:
    name: str
    role: str  # e.g. "霏霏", "樂樂", "同學", "老師"
    notes: str = ""  # short, concrete, no motive labels


@dataclass
class StoryObservation:
    text: str  # concrete observation sentence


@dataclass
class StoryScene:
    title: str
    narration: str
    observations: List[StoryObservation] = field(default_factory=list)


@dataclass
class StoryPackage:
    """Structured story output for the engine to consume.

    IMPORTANT:
    - No answers / no culprit.
    - Observations only, leave space.
    """
    case_id: str
    title: str

    # Required structure from your Story Generator Prompt:
    prologue: str  # "今天是什麼日子/哪裡/規則/重要性"
    characters: List[StoryCharacter]
    scenes: List[StoryScene]

    cooldown_dialogue: str  # 指認前情緒降溫對話
    teacher_scene: str      # 老師出現（結案前）
    open_ending: str        # 開放式收尾（不裁決）

    tags: List[str] = field(default_factory=list)  # e.g. ["排隊", "輪流", "貼紙"]


# -------------------------
# Interactive response
# -------------------------

Intent = Literal[
    "support_uncertain",
    "acknowledge_observation",
    "safe_redirect_after_accuse",
    "reflect_reasoning",
    "recall_event",
    "replay_context",
]

Role = Literal["narrator", "feifei", "lele", "teacher"]


@dataclass
class ResponseRequest:
    intent: Intent
    role: Role

    # Player / context
    player_text: str = ""  # free text input (optional)
    selected_observations: List[str] = field(default_factory=list)
    accused_name: str = ""  # if player accused someone (optional)

    # Short current context (keep minimal)
    scene_title: str = ""
    known_observations: List[str] = field(default_factory=list)


@dataclass
class ResponsePackage:
    """One response only. Must be 2-4 sentences, <=1 question."""
    intent: Intent
    role: Role
    text: str
