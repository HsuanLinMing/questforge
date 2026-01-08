from typing import Dict, Any
from questforge.core.models import DetectiveState


def apply_effects(state: DetectiveState, effects: Dict[str, Any] | None) -> None:
    """套用 choice effects 到偵探狀態。

    effects 支援：
    - add_clues: [str]
    - add_notes: [str]
    - set_flags: [str]
    - inc_vars: { key: int }
    """
    if not effects:
        return

    for clue in effects.get("add_clues", []):
        state.add_clue(clue)

    for note in effects.get("add_notes", []):
        state.add_note(note)

    for flag in effects.get("set_flags", []):
        state.set_flag(flag)

    for key, delta in effects.get("inc_vars", {}).items():
        state.inc(key, delta)
