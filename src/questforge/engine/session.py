# src/questforge/engine/session.py
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from questforge.core.models import DetectiveState, GameConfig
from questforge.engine.effects import apply_effects
from questforge.engine.views import NodeView, ChoiceView
from questforge.engine.actions import PlayerAction


@dataclass
class StepResult:
    view: Optional[NodeView]
    events: List[str]
    is_over: bool = False

    # ✅ 新增：讓 CLI / Flutter adapter 能知道「剛剛選了什麼、要去哪」
    selected_choice_index: int = 0
    selected_next: str = ""


class GameSession:
    def __init__(
        self,
        *,
        state: DetectiveState,
        nodes: Dict[str, Any],
        start_node: str,
        config: GameConfig,
    ):
        self.state = state
        self.nodes = nodes
        self.current = start_node
        self.config = config
        self._last_view_cache: Optional[NodeView] = None

    def get_view(self) -> NodeView:
        node = self.nodes[self.current]
        title = (node.get("title") or "").strip()
        narration = (node.get("narration") or "").strip()

        choices_raw = node.get("choices") or []
        choices: List[ChoiceView] = []
        for i, c in enumerate(choices_raw, start=1):
            choices.append(
                ChoiceView(
                    index=i,
                    text=(c.get("text") or "").strip(),
                    enabled=True,
                    reason=(c.get("after") or "").strip() or None,
                )
            )

        self._last_view_cache = NodeView(
            node_id=self.current,
            title=title,
            narration=narration,
            choices=choices,
        )
        return self._last_view_cache

    def step(self, action: PlayerAction) -> StepResult:
        events: List[str] = []

        if action.type == "quit":
            return StepResult(view=None, events=["玩家選擇離開"], is_over=True)

        if action.type == "replay":
            return StepResult(view=self.get_view(), events=["重播本段"], is_over=False)

        if action.type == "choose":
            view = self.get_view()
            idx = action.choice_index or 0
            if idx <= 0 or idx > len(view.choices):
                return StepResult(view=view, events=["無效選項"], is_over=False)

            node = self.nodes[self.current]
            choice = (node.get("choices") or [])[idx - 1]

            before_clues = set(self.state.clues)
            apply_effects(self.state, choice.get("effects"))
            gained = sorted(set(self.state.clues) - before_clues)
            for k in gained:
                events.append(f"獲得線索：{self.state.clue_labels.get(k, k)}")

            after = (choice.get("after") or "").strip()
            if after:
                events.append(f"推理短對話：{after}")

            next_id = (choice.get("next") or "").strip()
            if not next_id:
                return StepResult(
                    view=None,
                    events=events + ["故事結束"],
                    is_over=True,
                    selected_choice_index=idx,
                    selected_next="",
                )

            self.current = next_id
            return StepResult(
                view=self.get_view(),
                events=events,
                is_over=False,
                selected_choice_index=idx,
                selected_next=next_id,
            )

        return StepResult(view=self.get_view(), events=["未知動作"], is_over=False)
