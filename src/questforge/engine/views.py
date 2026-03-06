# src/questforge/engine/views.py
from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass(frozen=True)
class ChoiceView:
    index: int
    text: str
    enabled: bool = True
    reason: Optional[str] = None  # 你想要的「為什麼找到線索」短對話（可先接 after）
    tag: str = ""   # ✅ 新增：engine/ux 用的標籤

@dataclass(frozen=True)
class NodeView:
    node_id: str
    title: str
    narration: str
    choices: List[ChoiceView]
    meta: Optional[Dict[str, Any]] = None
    can_replay: bool = True
    can_quit: bool = True

@dataclass
class EndingCheckView:
    title: str
    narration: str
    options: List[tuple[str, str]] 