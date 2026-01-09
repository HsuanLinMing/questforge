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
    teacher_scene: str  # 老師出現（結案前）
    open_ending: str  # 開放式收尾（不裁決）

    tags: List[str] = field(default_factory=list)  # e.g. ["排隊", "輪流", "貼紙"]


# -------------------------
# Interactive response
# -------------------------

Intent = Literal[
    # Core interaction intents
    "support_uncertain",
    "acknowledge_observation",
    "safe_redirect_after_accuse",
    "reflect_reasoning",
    "replay_context",
    # Optional / legacy (keep for compatibility)
    "recall_event",
    # CLI transition intents (actually used)
    "back_from_clues",
    "back_from_notes",
    "back_from_saves",
    # CLI intents (Day13 planned / optional)
    "menu_opened",  # 打開線索/筆記/存檔等
    "replay_requested",  # 按 R
    "generic_ok",  # fallback（真的不知道時）
    "ending_feedback",   # ✅ Day15: ending_check 的 AI 推理回饋文字
]

Role = Literal["narrator", "feifei", "lele", "teacher"]


@dataclass
class ResponseRequest:
    intent: Intent
    role: Role

    # -------------------------
    # Player / context (existing, keep)
    # -------------------------
    player_text: str = ""  # free text input (optional)
    selected_observations: List[str] = field(default_factory=list)
    accused_name: str = ""  # if player accused someone (optional)

    # Short current context (keep minimal)
    scene_title: str = ""
    known_observations: List[str] = field(default_factory=list)

    # -------------------------
    # Day15+ safe additions (backward compatible)
    # -------------------------
    node_id: str = ""  # where this request is triggered (debuggable)
    turn: int = 0  # current turn (rhythm control)
    clues_preview: List[str] = field(default_factory=list)  # ONLY labels, no keys
    meta: Dict[str, Any] = field(default_factory=dict)  # reserved for future, safe JSON

    def __post_init__(self) -> None:
        """Normalize fields to keep downstream prompt/guard stable."""
        self.player_text = (self.player_text or "").strip()
        self.accused_name = (self.accused_name or "").strip()
        self.scene_title = (self.scene_title or "").strip()
        self.node_id = (self.node_id or "").strip()

        # Normalize lists (strip + drop empty + cap length to avoid prompt bloat)
        def _norm_list(xs: List[str], *, cap: int = 6) -> List[str]:
            out: List[str] = []
            for x in xs or []:
                s = (x or "").strip()
                if s:
                    out.append(s)
                if len(out) >= cap:
                    break
            return out

        self.selected_observations = _norm_list(self.selected_observations, cap=4)
        self.known_observations = _norm_list(self.known_observations, cap=6)
        self.clues_preview = _norm_list(self.clues_preview, cap=6)

        # Ensure meta is dict
        if self.meta is None:
            self.meta = {}
        if not isinstance(self.meta, dict):
            # best-effort: don't crash the game loop
            self.meta = {"_meta_raw": str(self.meta)}


@dataclass
class ResponsePackage:
    """One response only. Must be 2-4 sentences, <=1 question."""

    intent: Intent
    role: Role
    text: str
