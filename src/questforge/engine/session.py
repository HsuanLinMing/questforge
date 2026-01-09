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
from questforge.engine.easoning import score_reasons_with_evidence
from questforge.engine.effects import apply_effects
from questforge.engine.reasoning import evaluate_accuse
from questforge.engine.views import ChoiceView, NodeView
from questforge.engine.solve_rule_adapter import solve_rule_to_accuse_config



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
        reason_ids: List[str] | None = None,
        reason_text: str = "",
    ) -> ReasoningFeedback:
        result = AccuseResult(
            target=target,
            reason_ids=list(reason_ids or []),
            reason_id=(self.state.last_reason_id or ""),  # 相容舊 flow
            reason_text=reason_text,
        )
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
    # View
    # ----------------------------
    def get_view(self) -> NodeView:
        node = self.nodes[self.current]
        title = (node.get("title") or "").strip()
        narration = (node.get("narration") or "").strip()

        # ✅ ending_check 進入時，動態把推理回饋文字 append 到 narration
        if self.current == self._ending_check_node():
            accuse_config = solve_rule_to_accuse_config(self.solve_rule)

            result = AccuseResult(
                target=(self.state.last_accuse or "").strip(),
                reason_ids=list(self.state.last_reason_ids or []),
                reason_id=self.state.last_reason_id,
                reason_text=self.state.last_reason_text,
            )

            fb = evaluate_accuse(
                accuse_config,
                result,
                set(self.state.clues),
            )

            threshold = accuse_config.min_good_score

            extra_lines = [
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
                labels = [self.state.clue_labels.get(k, k) for k in fb.missing_key_evidence[:2]]
                extra_lines.append("可以再留意：" + "、".join(labels))

            # 揭曉（可選）
            if accuse_config.truth:
                last = (self.state.last_accuse or "").strip()
                if last == accuse_config.truth:
                    extra_lines.append("老師：最後查清楚了，你的方向很接近！")
                elif last:
                    extra_lines.append("老師：最後查清楚了，事情其實不是你一開始想的那樣。")
                else:
                    extra_lines.append("老師：你先把看到的說清楚，這樣最安全。")

            narration = narration + "\n" + "\n".join(extra_lines)

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
        reason_ids = self.state.last_reason_ids or []

        suspects = self.solve_rule.get("suspects", {}) or {}
        profile = suspects.get(chosen_suspect, {}) or {}
        support = profile.get("support", {}) or {}

        total_score, matched, missing = score_reasons_with_evidence(
            reason_ids=reason_ids,
            reason_options=self.solve_rule.get("reason_options", []),
            clues=set(self.state.clues),
            support_map=support,
        )


        # 永遠可指認：用分數分級回饋，不做卡關
        if threshold > 0 and total_score >= threshold:
            level = "good"
        elif threshold > 0 and total_score >= max(1, threshold // 2):
            level = "ok"
        else:
            level = "weak"

        if level == "good":
            events.append("霏霏：你的推理很完整，也有線索支持。")
        elif level == "ok":
            events.append("樂樂：你抓到一些重點了，再多一點線索會更清楚。")
        else:
            events.append("霏霏：你願意整理想法很棒，我們可以再多觀察一下。")

        if matched:
            labels = [self.state.clue_labels.get(k, k) for k in matched]
            events.append("你有用到的線索：" + "、".join(labels))

        if missing:
            labels = [self.state.clue_labels.get(k, k) for k in missing[:2]]
            events.append("可以再留意看看：" + "、".join(labels))

        # confirm_quiz：ok 以上再出（避免太吵）
        confirm = self.solve_rule.get("confirm_quiz", []) or []
        if (
            getattr(self.config, "enable_quiz", False)
            and confirm
            and (threshold <= 0 or total_score >= max(1, threshold // 2))
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
        # set_reasons (Day9: 多理由)
        # ----------------------------
        if action.type == "set_reasons":
            reason_ids = action.reason_ids or []

            # 相容寫法：先記在 state（Day9 之後會正式升級）
            self.state.last_reason_ids = list(reason_ids)
            self.state.last_reason_id = ""      # 舊欄位清空
            self.state.last_reason_text = ""

            reason_opts = self.solve_rule.get("reason_options") or []

            events = []
            seen_any = False
            missing_hints: List[str] = []

            for rid in reason_ids:
                opt = next(
                    (o for o in reason_opts if (o.get("id") or "").strip() == rid),
                    None,
                )
                if not opt:
                    continue

                text = (opt.get("text") or "").strip()
                events.append(f"霏霏：你注意到一件事是——「{text}」")

                expected = [str(x) for x in (opt.get("expected_evidence") or []) if x]
                got = [k for k in expected if k in self.state.clues]
                miss = [k for k in expected if k not in self.state.clues]

                if got:
                    seen_any = True
                    labels = [self.state.clue_labels.get(k, k) for k in got]
                    events.append("霏霏：這個想法有線索支持：" + "、".join(labels))

                if miss:
                    for k in miss[:1]:  # 每個理由最多提示一個
                        missing_hints.append(self.state.clue_labels.get(k, k))

            if not reason_ids:
                events.append(
                    "霏霏：你現在還不太確定，沒關係，我們也可以交給老師。"
                )
            elif not seen_any:
                events.append(
                    "霏霏：你願意整理想法很棒！我們可以再找一些更明確的線索。"
                )

            if missing_hints:
                events.append("霏霏：之後可以再留意看看：" + "、".join(missing_hints[:2]))

            # 回到 accuse，讓玩家選人（或不選）
            accuse_node = self._accuse_node() or "accuse"
            self.current = accuse_node
            return StepResult(view=self.get_view(), events=events, is_over=False)

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
        has_reason = bool(self.state.last_reason_ids)

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
