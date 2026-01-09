# src/questforge/engine/session.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from questforge.core.models import (
    AccuseConfig,
    AccuseResult,
    DetectiveState,
    GameConfig,
    ReasoningFeedback,
)
from questforge.engine.actions import PlayerAction
from questforge.engine.effects import apply_effects
from questforge.engine.reasoning import evaluate_accuse
from questforge.engine.solve_rule_engine import handle_ending_check
from questforge.engine.views import ChoiceView, NodeView


@dataclass
class StepResult:
    """一步推進的結果（引擎 → UI）。

    - view: 下一個要顯示的畫面（NodeView）
    - events: 本步驟產生的事件（CLI 可直接 print）
    - commands: 給 UI 的指令（例如 ask_reason / confirm_quiz）
    """

    view: Optional[NodeView]
    events: List[str]
    is_over: bool = False

    selected_choice_index: int = 0
    selected_next: str = ""

    commands: List[Dict[str, Any]] = field(default_factory=list)


class GameSession:
    """純邏輯遊戲流程控制器（不做 print/input）。

    Day8 重點（單理由版）：
    - 指認永遠可進（不卡關）
    - 進入 accuse 前可選擇先問理由（reason_node / ask_reason）
    - ending_check 會動態追加推理成熟度回饋
    """

    def __init__(
        self,
        *,
        state: DetectiveState,
        nodes: Dict[str, Any],
        start_node: str,
        config: GameConfig,
        solve_rule: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.state = state
        self.nodes = nodes
        self.current = start_node
        self.config = config
        self.solve_rule = solve_rule or {}
        self._last_view_cache: Optional[NodeView] = None

    # ----------------------------
    # Public: Accuse (optional, kept for future)
    # ----------------------------
    def accuse(
        self,
        accuse_config: AccuseConfig,
        target: str,
        reason_id: str,
        reason_text: str = "",
    ) -> ReasoningFeedback:
        """玩家指認：永遠可進，不卡關，只回饋推理成熟度。"""
        result = AccuseResult(target=target, reason_id=reason_id, reason_text=reason_text)
        return evaluate_accuse(accuse_config, result, self.state.clues)

    # ----------------------------
    # Helpers: node ids from solve_rule
    # ----------------------------
    def _reason_node(self) -> str:
        return (self.solve_rule.get("reason_node") or "").strip()

    def _accuse_node(self) -> str:
        return (self.solve_rule.get("accuse_node") or "").strip()

    def _ending_check_node(self) -> str:
        return (self.solve_rule.get("ending_check_node") or "ending_check").strip()

    # ----------------------------
    # Scoring (accuse)
    # ----------------------------
    def _score_suspect(self, suspect: str) -> int:
        suspects = (self.solve_rule.get("suspects") or {}) if self.solve_rule else {}
        profile = (suspects.get(suspect) or {}) if isinstance(suspects, dict) else {}
        support = (profile.get("support") or {}) if isinstance(profile, dict) else {}

        score = 0
        for ev in self.state.clues:
            score += int(support.get(ev, 0) or 0)
        return score

    # ----------------------------
    # View
    # ----------------------------
    def get_view(self) -> NodeView:
        node = self.nodes[self.current]
        title = (node.get("title") or "").strip()
        narration = (node.get("narration") or "").strip()

        # ✅ ending_check 進入時，動態把推理回饋文字 append 到 narration
        if self.current == self._ending_check_node():
            fb = handle_ending_check(
                solve_rule=self.solve_rule,
                target=(self.state.last_accuse or "").strip(),
                clues=set(self.state.clues),
            )
            threshold = int((self.solve_rule.get("threshold", 0)) or 0)

            extra_lines: List[str] = [
                "",
                "—",
                f"【推理回饋】成熟度：{fb.level}"
                + (f"｜分數：{fb.score}/{threshold}" if threshold > 0 else ""),
                fb.message,
            ]

            if fb.matched_evidence:
                labels = [self.state.clue_labels.get(k, k) for k in fb.matched_evidence]
                extra_lines.append("你有用到的線索：" + "、".join(labels))

            if fb.level != "good" and fb.missing_key_evidence:
                hint = [self.state.clue_labels.get(k, k) for k in fb.missing_key_evidence[:2]]
                extra_lines.append("可以再留意：" + "、".join(hint))

            # ✅ 揭曉引導（不判對錯，只溫柔說明）
            correct = (self.solve_rule.get("correct_suspect") or "").strip()
            if correct:
                last = (self.state.last_accuse or "").strip()
                if last == correct:
                    extra_lines.append("老師：最後查清楚了，你的方向很接近！")
                elif last:
                    extra_lines.append("老師：最後查清楚了，事情其實不是你一開始想的那樣。")
                else:
                    extra_lines.append("老師：你先把看到的說清楚，這樣最安全。")

            narration = narration + "\n" + "\n".join([s for s in extra_lines if s])

        # choices（注意：reason_node 會被當作「純 ask_reason 節點」，UI 不應使用它 choices）
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

    # ----------------------------
    # Internal: ask reason command
    # ----------------------------
    def _make_ask_reason_command(self) -> Dict[str, Any]:
        mode = getattr(self.config, "reason_input_mode", "choice")
        reason_opts = self.solve_rule.get("reason_options") or []
        return {"type": "ask_reason", "mode": mode, "options": reason_opts}

    # ----------------------------
    # Internal: choice apply (effects/evidence/after/accuse record)
    # ----------------------------
    def _apply_choice_effects_and_collect_events(self, choice: Dict[str, Any], events: List[str]) -> None:
        """effects + evidence + after，並把「獲得線索/短對話」寫進 events。"""
        before_clues = set(self.state.clues)

        # 1) effects
        apply_effects(self.state, choice.get("effects"))

        # 2) evidence（key/label）
        for ev in choice.get("evidence") or []:
            self.state.add_clue_with_label(ev.get("key", ""), ev.get("label"))

        # 3) gained clues（只列出本次新增）
        gained = sorted(set(self.state.clues) - before_clues)
        for k in gained:
            events.append(f"獲得線索：{self.state.clue_labels.get(k, k)}")

        # 4) after short dialogue
        after = (choice.get("after") or "").strip()
        if after:
            events.append(f"推理短對話：{after}")

        # 5) accuse record（永遠可指認：只記錄玩家選了誰）
        if "accuse" in choice:
            self.state.last_accuse = (choice.get("accuse") or "").strip()

    # ----------------------------
    # Internal: accuse feedback (only when currently at accuse_node)
    # ----------------------------
    def _handle_accuse_if_needed(
        self,
        *,
        current_node: str,
        next_id: str,
        events: List[str],
        commands: List[Dict[str, Any]],
    ) -> str:
        """在 accuse_node 做回饋（不阻擋，只引導）。回傳最終 next_id。"""
        accuse_node = self._accuse_node()
        if not accuse_node:
            return next_id
        if current_node != accuse_node:
            return next_id

        ending_check = self._ending_check_node()
        chosen_suspect = (self.state.last_accuse or "").strip()

        # 不確定也允許：直接進 ending_check
        if not chosen_suspect:
            events.append("霏霏：交給老師處理是很安全的選擇！我們把看到的線索整理清楚就好。")
            return ending_check

        threshold = int(self.solve_rule.get("threshold", 0) or 0)
        score = self._score_suspect(chosen_suspect)

        # 永遠可指認：用分數分級回饋，不做卡關
        if threshold > 0 and score >= threshold:
            events.append("霏霏：嗯…你的想法很有根據。我們把『看到的』整理好，再交給老師最安全。")
        elif threshold > 0 and score >= max(1, threshold // 2):
            events.append("樂樂：你的想法有一些根據喔！如果再找到一個關鍵點，你會更有把握。")
        else:
            events.append("霏霏：你願意說出你的想法很棒！我們可以再觀察一下，找更明確的線索。")

        # confirm_quiz：ok 以上再出（避免太吵）
        confirm = self.solve_rule.get("confirm_quiz", []) or []
        if (
            getattr(self.config, "enable_quiz", False)
            and confirm
            and (threshold <= 0 or score >= max(1, threshold // 2))
        ):
            commands.append({"type": "confirm_quiz", "quiz": confirm})

        return ending_check

    # ----------------------------
    # Step
    # ----------------------------
    def step(self, action: PlayerAction) -> StepResult:
        events: List[str] = []
        commands: List[Dict[str, Any]] = []

        # ----------------------------
        # set_reason (UI -> Engine)
        # ----------------------------
        if action.type == "set_reason":
            rid = (action.reason_id or "").strip() or "unspecified"
            rtext = (action.reason_text or "").strip()

            self.state.last_reason_id = rid
            self.state.last_reason_text = rtext

            # ✅ 立即回饋：讓孩子知道「理由已被聽到」
            reason_opts = self.solve_rule.get("reason_options") or []
            opt = next((o for o in reason_opts if (o.get("id") or "").strip() == rid), None)

            if opt:
                events.append(f"霏霏：好，我記下你的理由：『{(opt.get('text') or '').strip()}』")
                expected = [str(x) for x in (opt.get("expected_evidence") or []) if x]
                if expected:
                    got = [k for k in expected if k in self.state.clues]
                    miss = [k for k in expected if k not in self.state.clues]
                    if got:
                        labels = [self.state.clue_labels.get(k, k) for k in got]
                        events.append("霏霏：你確實有看到：" + "、".join(labels))
                    if miss:
                        labels = [self.state.clue_labels.get(k, k) for k in miss[:2]]
                        events.append("霏霏：還有一兩個小細節我們沒看到，可以再留意：" + "、".join(labels))
            else:
                if rtext:
                    events.append(f"霏霏：好，我記下你說的理由：『{rtext}』")
                else:
                    events.append("霏霏：好，我記下你現在還說不太清楚，我們也可以交給老師處理。")

            # ✅ 回到 accuse，讓玩家選嫌疑人
            accuse_node = self._accuse_node() or "accuse"
            self.current = accuse_node
            return StepResult(view=self.get_view(), events=events, is_over=False, selected_next=self.current)

        # ----------------------------
        # basic actions
        # ----------------------------
        if action.type == "quit":
            return StepResult(view=None, events=["玩家選擇離開"], is_over=True)

        if action.type == "replay":
            return StepResult(view=self.get_view(), events=["重播本段"], is_over=False)

        if action.type != "choose":
            return StepResult(view=self.get_view(), events=["未知動作"], is_over=False)

        # ----------------------------
        # reason_node: treat as "ask_reason only" node (DO NOT consume story choices here)
        # ----------------------------
        reason_node = self._reason_node()
        if reason_node and self.current == reason_node:
            commands.append(self._make_ask_reason_command())
            return StepResult(
                view=self.get_view(),
                events=events,
                is_over=False,
                selected_choice_index=0,
                selected_next=self.current,
                commands=commands,
            )

        # ----------------------------
        # choose (normal)
        # ----------------------------
        view = self.get_view()
        idx = action.choice_index or 0
        if idx <= 0 or idx > len(view.choices):
            return StepResult(view=view, events=["無效選項"], is_over=False)

        # ✅ choose 才算一回合
        self.state.turn += 1

        node = self.nodes[self.current]
        choice = (node.get("choices") or [])[idx - 1]

        # 1) effects/evidence/after -> events
        self._apply_choice_effects_and_collect_events(choice, events)

        # 2) next
        next_id = (choice.get("next") or "").strip()
        if not next_id:
            return StepResult(
                view=None,
                events=events + ["故事結束"],
                is_over=True,
                selected_choice_index=idx,
                selected_next="",
                commands=commands,
            )

        accuse_node = self._accuse_node()
        has_reason = bool((self.state.last_reason_id or "").strip())

        # ----------------------------
        # ✅ Gate: going to accuse -> ask reason first (if configured & not yet provided)
        # ----------------------------
        if accuse_node and reason_node and next_id == accuse_node and not has_reason:
            self.current = reason_node
            commands.append(self._make_ask_reason_command())
            return StepResult(
                view=self.get_view(),
                events=events,
                is_over=False,
                selected_choice_index=idx,
                selected_next=self.current,
                commands=commands,
            )

        # 3) accuse feedback（只在 accuse_node 生效；通常會導向 ending_check）
        final_next = self._handle_accuse_if_needed(
            current_node=self.current,
            next_id=next_id,
            events=events,
            commands=commands,
        )

        # 4) apply next
        self.current = final_next

        # 5) entering accuse_node: reset reason（新一輪）
        if accuse_node and self.current == accuse_node:
            self.state.last_reason_id = ""
            self.state.last_reason_text = ""

        return StepResult(
            view=self.get_view(),
            events=events,
            is_over=False,
            selected_choice_index=idx,
            selected_next=self.current,
            commands=commands,
        )

    # ----------------------------
    # Save / Load
    # ----------------------------
    def export_snapshot(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "state": self.state.to_dict(),
            "session": {"current": self.current},
        }


def restore_session_from_snapshot(
    *,
    snapshot: Dict[str, Any],
    nodes: Dict[str, Any],
    config: GameConfig,
    solve_rule: Optional[Dict[str, Any]] = None,
) -> GameSession:
    """從 snapshot 還原 GameSession（避免 classmethod 不存在造成讀檔失敗）。"""
    state = DetectiveState.from_dict(snapshot.get("state", {}) or {})
    current = str((snapshot.get("session") or {}).get("current") or "").strip()
    if not current or current not in nodes:
        current = next(iter(nodes.keys()))
    return GameSession(
        state=state,
        nodes=nodes,
        start_node=current,
        config=config,
        solve_rule=solve_rule or {},
    )
