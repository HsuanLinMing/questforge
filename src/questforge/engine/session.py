# src/questforge/engine/session.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from questforge.ai import AiClient, MockAiClient
from questforge.ai.schemas import ResponsePackage, ResponseRequest, StoryPackage
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
from questforge.engine.solve_rule_adapter import solve_rule_to_accuse_config
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

    - 指認永遠可進（不卡關）
    - going to accuse 時可先 ask_reason（reason_node / command）
    - ending_check 追加「反思型」推理回饋（不裁決、不揭曉）
    """

    def __init__(
        self,
        *,
        state: DetectiveState,
        nodes: Dict[str, Any],
        start_node: str,
        config: GameConfig,
        solve_rule: Optional[Dict[str, Any]] = None,
        ai: Optional[AiClient] = None,
    ) -> None:
        self.state = state
        self.nodes = nodes
        self.current = start_node
        self.config = config
        self.solve_rule = solve_rule or {}
        self._last_view_cache: Optional[NodeView] = None

        # ✅ Day12-A: AI client injection (default to Mock)
        self.ai: AiClient = ai or MockAiClient()

    # ----------------------------
    # AI (Day12-A)
    # ----------------------------
    def generate_new_case(self) -> StoryPackage:
        return self.ai.generate_story()

    def say(self, req: ResponseRequest) -> ResponsePackage:
        return self.ai.generate_response(req)

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

        # ✅ ending_check：只做反思回饋，不裁決、不揭曉 truth
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

            extra_lines: List[str] = [
                "",
                "—",
                "【推理回饋】這不是判對錯，是幫你整理思路。",
                f"成熟度：{fb.level}"
                + (f"｜分數：{fb.score}/{threshold}" if threshold > 0 else ""),
                fb.message,
            ]

            if fb.matched_evidence:
                labels = [self.state.clue_labels.get(k, k) for k in fb.matched_evidence]
                extra_lines.append("你有用到的線索：" + "、".join(labels))

            if fb.level != "good" and fb.missing_key_evidence:
                labels = [
                    self.state.clue_labels.get(k, k)
                    for k in fb.missing_key_evidence[:2]
                ]
                extra_lines.append("可以再留意：" + "、".join(labels))

            # ✅ 安全出口（不確定是被支持的）
            if not (self.state.last_accuse or "").strip():
                extra_lines.append("老師：你願意先說『不確定』很安全，我們一起再確認。")
            else:
                extra_lines.append("老師：謝謝你把看到的整理出來，我們會一起再確認。")

            narration = narration + "\n" + "\n".join(extra_lines)

        # choices
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
    def _apply_choice_effects_and_collect_events(
        self, choice: Dict[str, Any], events: List[str]
    ) -> None:
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
            events.append(
                "霏霏：你先選『不確定』很安全，我們把看到的整理清楚交給老師就好。"
            )
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

        # ✅ Day12-B Step 4: 用 AI 產生「指認後的安全導回」回應（只說一次）
        resp = self.say(
            ResponseRequest(
                intent="safe_redirect_after_accuse",
                role="feifei",
                accused_name=chosen_suspect,
                # 讓 AI 有材料可以提到「你用了哪些觀察」（但仍不下結論）
                selected_observations=[
                    (opt.get("text") or "").strip()
                    for opt in (self.solve_rule.get("reason_options") or [])
                    if (opt.get("id") or "").strip() in (reason_ids or [])
                ],
            )
        )
        events.append(resp.text)

        # ✅ 具體線索回饋：仍由 engine 控制（避免 AI 自己加戲）
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
        # set_reasons (Day12-B step 1: response via AI)
        # ----------------------------
        if action.type == "set_reasons":
            reason_ids = action.reason_ids or []

            # 記錄狀態（邏輯不變）
            self.state.last_reason_ids = list(reason_ids)
            self.state.last_reason_id = ""
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

                # ✅ NEW: 用 AI 產生「確認觀察」的回應
                resp = self.say(
                    ResponseRequest(
                        intent="acknowledge_observation",
                        role="feifei",
                        selected_observations=[text],
                    )
                )
                events.append(resp.text)

                # === 以下邏輯完全保留（不是 AI 負責） ===
                expected = [str(x) for x in (opt.get("expected_evidence") or []) if x]
                got = [k for k in expected if k in self.state.clues]
                miss = [k for k in expected if k not in self.state.clues]

                if got:
                    seen_any = True
                    labels = [self.state.clue_labels.get(k, k) for k in got]
                    events.append("霏霏：這個想法有線索支持：" + "、".join(labels))

                if miss:
                    for k in miss[:1]:
                        missing_hints.append(self.state.clue_labels.get(k, k))

            # ✅ Day12-B Step 3（修正版）：reflect_reasoning 只說一次
            if not reason_ids:
                # 不確定：support_uncertain
                resp = self.say(
                    ResponseRequest(
                        intent="support_uncertain",
                        role="feifei",
                        player_text="我不確定",
                    )
                )
                events.append(resp.text)

            elif not seen_any:
                # 選了理由但還沒有 evidence：先做一次「反思型」AI 回應
                resp = self.say(
                    ResponseRequest(
                        intent="reflect_reasoning",
                        role="feifei",
                        selected_observations=[
                            (opt.get("text") or "").strip()
                            for opt in reason_opts
                            if (opt.get("id") or "").strip() in reason_ids
                        ],
                    )
                )
                events.append(resp.text)

                # 再補「可以留意的具體線索」（這段是 engine，不是 AI）
                if missing_hints:
                    labels = "、".join(missing_hints[:2])
                    events.append(f"霏霏：之後可以再留意看看：{labels}")

            # 回到 accuse（流程不變）
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
        # reason_node: treat as "ask_reason only" node
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

        # ✅ Gate: going to accuse -> ask reason first (if configured & not yet provided)
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

        # 3) accuse feedback
        final_next = self._handle_accuse_if_needed(
            current_node=self.current,
            next_id=next_id,
            events=events,
            commands=commands,
        )

        # 4) apply next
        self.current = final_next

        # 5) entering accuse_node: reset reason (new round)
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
    ai: Optional[AiClient] = None,
) -> GameSession:
    """從 snapshot 還原 GameSession。"""
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
        ai=ai,
    )
