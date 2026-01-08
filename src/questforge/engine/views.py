# src/questforge/engine/views.py
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ChoiceView:
    index: int
    text: str
    enabled: bool = True
    reason: Optional[str] = None  # 你想要的「為什麼找到線索」短對話（可先接 after）


@dataclass(frozen=True)
class NodeView:
    node_id: str
    title: str
    narration: str
    choices: List[ChoiceView]
    can_replay: bool = True
    can_quit: bool = True
