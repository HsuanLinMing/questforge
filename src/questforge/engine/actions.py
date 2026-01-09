# src/questforge/engine/actions.py
from dataclasses import dataclass
from typing import List, Literal, Optional
ActionType = Literal["choose", "replay", "quit", "set_reason", "set_reasons"]


@dataclass(frozen=True)
class PlayerAction:
    type: ActionType
    choice_index: Optional[int] = None  # type == "choose" 時用
    reason_id: Optional[str] = None
    reason_text: Optional[str] = None
    reason_ids: Optional[List[str]] = None
