# src/questforge/engine/actions.py
from dataclasses import dataclass
from typing import Literal, Optional
ActionType = Literal["choose", "replay", "quit", "set_reason"]


@dataclass(frozen=True)
class PlayerAction:
    type: ActionType
    choice_index: Optional[int] = None  # type == "choose" 時用
    reason_id: str = ""
    reason_text: str = ""
