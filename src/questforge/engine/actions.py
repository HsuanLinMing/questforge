# src/questforge/engine/actions.py
from dataclasses import dataclass
from typing import List, Literal, Optional, Any
ActionType = Literal["choose", "replay", "quit", "set_reason", "set_reasons", "confirm_quiz_answer", "end_flow"]


@dataclass(frozen=True)
class PlayerAction:
    type: ActionType
    choice_index: Optional[int] = None  # type == "choose" 時用

    reason_id: Optional[str] = None
    reason_text: Optional[str] = None
    reason_ids: Optional[List[str]] = None

    # ✅ confirm_quiz_answer
    answers: Optional[List[Any]] = None
    skipped: bool = False

    # end_flow (Day16-C)
    end_action: str = ""  # go_epilogue / restart_case / switch_case / quit
