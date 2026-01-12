# src/questforge/engine/actions.py
from dataclasses import dataclass
from typing import List, Literal, Optional
ActionType = Literal["choose", "replay", "quit", "set_reason", "set_reasons", "end_flow"]


@dataclass(frozen=True)
class PlayerAction:
    
    type: ActionType
    choice_index: Optional[int] = None  # type == "choose" 時用
    reason_id: Optional[str] = None
    reason_text: Optional[str] = None
    reason_ids: Optional[List[str]] = None
    # end_flow (Day16-C)
    end_action: str = ""  # go_epilogue / restart_case / switch_case / quit
