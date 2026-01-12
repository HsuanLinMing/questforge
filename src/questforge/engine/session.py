# src/questforge/engine/session.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from questforge.ai.ai_client import AiClient, build_ai_client
from questforge.ai.guard_log import log_guard_result
from questforge.ai.response_guard import guard_response
from questforge.ai.schemas import ResponsePackage, ResponseRequest, StoryPackage
from questforge.core.models import (
    AccuseConfig,
    AccuseResult,
    DetectiveState,
    GameConfig,
    ReasoningFeedback,
)
from questforge.engine.actions import PlayerAction
from questforge.engine.effects import apply_effects
from questforge.engine.reasoning import evaluate_accuse, score_reasons_with_evidence
from questforge.engine.solve_rule_adapter import solve_rule_to_accuse_config
from questforge.engine.views import ChoiceView, NodeView


@dataclass
class StepResult:
    """一步推進的結果（引擎 → UI）。"""

    view: Optional[Any]
    events: List[str]
    is_over: bool = False

    selected_choice_index: int = 0
    selected_next: str = ""
    commands: List[Dict[str, Any]] = field(default_factory=list)


class GameSession:
    """純邏輯遊戲流程控制器（不做 print/input）。

    A) Tag 化：用 node.tag 判斷最後調查點 last_investigate_node
    B) 結案流程：ending_result / ending_wrong / epilogue 由 engine 注入 Flow choices
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

        # 用於「回到調查」fallback
        self._start_node_id: str = start_node

        # AI
        self.ai: AiClient = ai or build_ai_client()
        self._last_ai_text_by_intent: Dict[str, str] = {}

        # 保留：進入 ending_check 前的節點（你要用也行）
        self.last_play_node: str = start_node
        # A) 真正用來回到調查的節點（只記 investigate 節點）
        self.last_investigate_node: str = start_node

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
    # Helpers: node tags
    # ----------------------------
    def _node_tag(self, node_id: str) -> str:
        try:
            return (self.nodes.get(node_id, {}).get("tag") or "").strip()
        except Exception:
            return ""

    def _is_tag(self, node_id: str, tag: str) -> bool:
        return self._node_tag(node_id) == tag

    def _is_investigate_node(self, node_id: str) -> bool:
        return self._is_tag(node_id, "investigate")

    def _is_ending_result_node(self, node_id: str) -> bool:
        return self._is_tag(node_id, "ending_result")

    def _is_ending_wrong_node(self, node_id: str) -> bool:
        return self._is_tag(node_id, "ending_wrong")

    def _is_epilogue_node(self, node_id: str) -> bool:
        return self._is_tag(node_id, "epilogue")

    # ----------------------------
    # AI
    # ----------------------------
    def generate_new_case(self) -> StoryPackage:
        return self.ai.generate_story()

    def say(self, req: ResponseRequest) -> ResponsePackage:
        try:
            if not getattr(req, "scene_title", ""):
                req.scene_title = (
                    self.nodes.get(self.current, {}).get("title") or ""
                ).strip()
            if not getattr(req, "node_id", ""):
                req.node_id = (self.current or "").strip()
            if not getattr(req, "turn", 0):
                req.turn = int(getattr(self.state, "turn", 0) or 0)
            if not getattr(req, "clues_preview", None):
                req.clues_preview = [
                    self.state.clue_labels.get(k, k) for k in sorted(self.state.clues)
                ]
        except Exception:
            pass

        pkg = self.ai.generate_response(req)

        gr = guard_response(pkg.text)
        log_guard_result(req=req, pkg=pkg, gr=gr)

        if (not gr.ok) or gr.warnings:
            print("\n[AI 白名單檢查]")
            if not gr.ok:
                for e in gr.errors:
                    print(f"  ❌ {e}")
            for w in gr.warnings:
                print(f"  ⚠️ {w}")

        return pkg

    def say_once(self, req: ResponseRequest) -> ResponsePackage:
        last = self._last_ai_text_by_intent.get(req.intent, "")
        pkg: ResponsePackage = self.say(req)

        if last and pkg.text.strip() == last.strip():
            for _ in range(2):
                pkg2 = self.say(req)
                if pkg2.text.strip() != last.strip():
                    pkg = pkg2
                    break

        self._last_ai_text_by_intent[req.intent] = pkg.text
        return pkg

    # ----------------------------
    # Accuse (optional)
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
            reason_id=(self.state.last_reason_id or ""),
            reason_text=reason_text,
        )
        return evaluate_accuse(accuse_config, result, self.state.clues)

    # ----------------------------
    # View builders (Flow)
    # ----------------------------
    def _flow_choices_for_epilogue(self) -> List[ChoiceView]:
        # Flutter 之後直接畫三顆按鈕就好
        return [
            ChoiceView(
                index=1,
                text="再玩一次這個案件",
                enabled=True,
                reason=None,
                tag="flow:restart_case",
            ),
            ChoiceView(
                index=2,
                text="玩下一個案件",
                enabled=True,
                reason=None,
                tag="flow:switch_case",
            ),
            ChoiceView(
                index=3, text="離開", enabled=True, reason=None, tag="flow:quit"
            ),
        ]

    def _flow_choices_for_endings(self) -> List[ChoiceView]:
        # ending_result / ending_wrong 統一：進尾聲
        return [
            ChoiceView(
                index=1,
                text="進入尾聲",
                enabled=True,
                reason=None,
                tag="flow:go_epilogue",
            ),
        ]

    # ----------------------------
    # View
    # ----------------------------
    def get_view(self) -> NodeView:
        node = self.nodes[self.current]
        title = (node.get("title") or "").strip()
        narration = (node.get("narration") or "").strip()

        # 1) ending_check：追加推理回饋 + 注入「回到調查」
        if self.current == self._ending_check_node():
            narration = self._normalize_duo_narration(narration)

            accuse_config = solve_rule_to_accuse_config(self.solve_rule)
            result = AccuseResult(
                target=(self.state.last_accuse or "").strip(),
                reason_ids=list(self.state.last_reason_ids or []),
                reason_id=self.state.last_reason_id,
                reason_text=self.state.last_reason_text,
            )

            fb = evaluate_accuse(accuse_config, result, set(self.state.clues))
            threshold = accuse_config.min_good_score

            extra_lines: List[str] = [
                "",
                "—",
                "【推理回饋】這不是判對錯，是幫你整理思路。",
                f"成熟度：{fb.level}"
                + (f"｜分數：{fb.score}/{threshold}" if threshold > 0 else ""),
            ]

            ai_resp = self.say_once(
                ResponseRequest(
                    intent="ending_feedback",
                    role="teacher",
                    scene_title=title,
                    node_id=self.current,
                    turn=self.state.turn,
                    clues_preview=[
                        self.state.clue_labels.get(k, k)
                        for k in sorted(list(self.state.clues))[:6]
                    ],
                    meta={
                        "level": fb.level,
                        "score": fb.score,
                        "threshold": threshold,
                        "matched_evidence": [
                            self.state.clue_labels.get(k, k)
                            for k in (fb.matched_evidence or [])
                        ],
                        "missing_key_evidence": [
                            self.state.clue_labels.get(k, k)
                            for k in (fb.missing_key_evidence or [])
                        ],
                        "engine_message": (fb.message or "").strip(),
                    },
                )
            )

            extra_lines.append(
                ai_resp.text.strip() if ai_resp.text.strip() else "我們慢慢來就好。"
            )

            if fb.matched_evidence:
                labels = [self.state.clue_labels.get(k, k) for k in fb.matched_evidence]
                extra_lines.append("你有用到的線索：" + "、".join(labels))

            if fb.level != "good" and fb.missing_key_evidence:
                labels = [
                    self.state.clue_labels.get(k, "")
                    for k in fb.missing_key_evidence[:2]
                ]
                labels = [x for x in labels if x]
                if labels:
                    extra_lines.append("可以再留意：" + "、".join(labels))

            extra_lines.append("老師：謝謝你把看到的整理出來，我們會一起再確認。")
            narration = narration + "\n" + "\n".join(extra_lines)

            # story 原生 choices（保留 story 自己的「安全結案」那顆）
            choices_raw = node.get("choices") or []
            choices: List[ChoiceView] = []
            for i, c in enumerate(choices_raw, start=1):
                choices.append(
                    ChoiceView(
                        index=i,
                        text=(c.get("text") or "").strip(),
                        enabled=True,
                        reason=(c.get("after") or "").strip() or None,
                        tag="",  # story choice
                    )
                )

            # 注入「回到調查」：用 last_investigate_node
            inv = (self.last_investigate_node or "").strip()
            if inv and inv in self.nodes and inv != self._ending_check_node():
                choices.append(
                    ChoiceView(
                        index=len(choices) + 1,
                        text="回到調查（再看看現場）",
                        enabled=True,
                        reason=None,
                        tag="ux:back_to_investigate",
                    )
                )

            self._last_view_cache = NodeView(
                node_id=self.current,
                title=title,
                narration=narration,
                choices=choices,
            )
            return self._last_view_cache

        # 2) ending_result：engine flow choices
        if self._is_ending_result_node(self.current):
            choices = self._flow_choices_for_endings()
            self._last_view_cache = NodeView(
                node_id=self.current,
                title=title,
                narration=narration,
                choices=choices,
            )
            return self._last_view_cache

        # 3) ending_wrong：engine flow choices（同 ending_result）
        if self._is_ending_wrong_node(self.current):
            choices = self._flow_choices_for_endings()
            self._last_view_cache = NodeView(
                node_id=self.current,
                title=title,
                narration=narration,
                choices=choices,
            )
            return self._last_view_cache

        # 4) epilogue：engine flow choices
        if self._is_epilogue_node(self.current):
            choices = self._flow_choices_for_epilogue()
            self._last_view_cache = NodeView(
                node_id=self.current,
                title=title,
                narration=narration,
                choices=choices,
            )
            return self._last_view_cache

        # 5) Normal NodeView
        choices_raw = node.get("choices") or []
        choices: List[ChoiceView] = []
        for i, c in enumerate(choices_raw, start=1):
            choices.append(
                ChoiceView(
                    index=i,
                    text=(c.get("text") or "").strip(),
                    enabled=True,
                    reason=(c.get("after") or "").strip() or None,
                    tag="",  # story choice
                )
            )

        self._last_view_cache = NodeView(
            node_id=self.current,
            title=title,
            narration=narration,
            choices=choices,
        )
        return self._last_view_cache

    @staticmethod
    def _normalize_duo_narration(text: str) -> str:
        pairs = [
            ("我慢慢說：", "我們慢慢說："),
            ("我補一句：", "我們補一句："),
            ("我看到", "我們看到"),
            ("我也看到", "我們也看到"),
            ("我覺得", "我們覺得"),
            ("我不確定", "我們不確定"),
        ]
        out = text or ""
        for a, b in pairs:
            out = out.replace(a, b)
        return out

    # ----------------------------
    # Internal: ask reason command
    # ----------------------------
    def _make_ask_reason_command(self) -> Dict[str, Any]:
        mode = getattr(self.config, "reason_input_mode", "choice")
        reason_opts = self.solve_rule.get("reason_options") or []
        return {"type": "ask_reason", "mode": mode, "options": reason_opts}

    # ----------------------------
    # Internal: apply choice
    # ----------------------------
    def _apply_choice_effects_and_collect_events(
        self, choice: Dict[str, Any], events: List[str]
    ) -> None:
        before_clues = set(self.state.clues)

        apply_effects(self.state, choice.get("effects"))

        for ev in choice.get("evidence") or []:
            self.state.add_clue_with_label(ev.get("key", ""), ev.get("label"))

        gained = sorted(set(self.state.clues) - before_clues)
        for k in gained:
            events.append(f"獲得線索：{self.state.clue_labels.get(k, k)}")

        after = (choice.get("after") or "").strip()
        if after:
            events.append(f"推理短對話：{after}")

        if "accuse" in choice:
            self.state.last_accuse = (choice.get("accuse") or "").strip()

    # ----------------------------
    # Internal: accuse feedback
    # ----------------------------
    def _handle_accuse_if_needed(
        self,
        *,
        current_node: str,
        next_id: str,
        events: List[str],
        commands: List[Dict[str, Any]],
    ) -> str:
        accuse_node = self._accuse_node()
        if not accuse_node or current_node != accuse_node:
            return next_id

        ending_check = self._ending_check_node()
        chosen_suspect = (self.state.last_accuse or "").strip()

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

        resp = self.say_once(
            ResponseRequest(
                intent="safe_redirect_after_accuse",
                role="feifei",
                accused_name=chosen_suspect,
                selected_observations=[
                    (opt.get("text") or "").strip()
                    for opt in (self.solve_rule.get("reason_options") or [])
                    if (opt.get("id") or "").strip() in (reason_ids or [])
                ],
                node_id=self.current,
                turn=self.state.turn,
                scene_title=(
                    self.nodes.get(self.current, {}).get("title") or ""
                ).strip(),
                clues_preview=[
                    self.state.clue_labels.get(k, k) for k in sorted(self.state.clues)
                ][:6],
            )
        )
        if resp.text.strip():
            events.append(resp.text)

        if matched:
            labels = [self.state.clue_labels.get(k, k) for k in matched]
            events.append("你有用到的線索：" + "、".join(labels))

        if missing:
            labels = [self.state.clue_labels.get(k, k) for k in missing[:2]]
            events.append("可以再留意看看：" + "、".join(labels))

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
        # set_reasons (Day12-B)
        # ----------------------------
        if action.type == "set_reasons":
            reason_ids = action.reason_ids or []

            self.state.last_reason_ids = list(reason_ids)
            self.state.last_reason_id = ""
            self.state.last_reason_text = ""

            reason_opts = self.solve_rule.get("reason_options") or []

            events = []
            seen_any = False
            missing_hints: List[str] = []

            for rid in reason_ids:
                opt = next(
                    (o for o in reason_opts if (o.get("id") or "").strip() == rid), None
                )
                if not opt:
                    continue

                text = (opt.get("text") or "").strip()

                resp = self.say_once(
                    ResponseRequest(
                        intent="acknowledge_observation",
                        role="feifei",
                        selected_observations=[text],
                        node_id=self.current,
                        turn=self.state.turn,
                        scene_title=(
                            self.nodes.get(self.current, {}).get("title") or ""
                        ).strip(),
                        clues_preview=[
                            self.state.clue_labels.get(k, k)
                            for k in sorted(self.state.clues)
                        ][:6],
                    )
                )
                if resp.text.strip():
                    events.append(resp.text)

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

            if not reason_ids:
                resp = self.say_once(
                    ResponseRequest(
                        intent="support_uncertain",
                        role="feifei",
                        player_text="我不確定",
                        node_id=self.current,
                        turn=self.state.turn,
                        scene_title=(
                            self.nodes.get(self.current, {}).get("title") or ""
                        ).strip(),
                        clues_preview=[
                            self.state.clue_labels.get(k, k)
                            for k in sorted(self.state.clues)
                        ][:6],
                    )
                )
                if resp.text.strip():
                    events.append(resp.text)

            elif not seen_any:
                resp = self.say_once(
                    ResponseRequest(
                        intent="reflect_reasoning",
                        role="feifei",
                        selected_observations=[
                            (opt.get("text") or "").strip()
                            for opt in reason_opts
                            if (opt.get("id") or "").strip() in reason_ids
                        ],
                        node_id=self.current,
                        turn=self.state.turn,
                        scene_title=(
                            self.nodes.get(self.current, {}).get("title") or ""
                        ).strip(),
                        clues_preview=[
                            self.state.clue_labels.get(k, k)
                            for k in sorted(self.state.clues)
                        ][:6],
                    )
                )
                if resp.text.strip():
                    events.append(resp.text)

                if missing_hints:
                    labels = "、".join(missing_hints[:2])
                    events.append(f"霏霏：之後可以再留意看看：{labels}")

            accuse_node = self._accuse_node() or "accuse"
            self.current = accuse_node
            return StepResult(
                view=self.get_view(), events=events, is_over=False, commands=commands
            )

        # basic actions
        if action.type == "quit":
            return StepResult(view=None, events=["玩家選擇離開"], is_over=True)

        if action.type == "replay":
            resp = self.say_once(
                ResponseRequest(
                    intent="replay_context",
                    role="feifei",
                    scene_title=(
                        self.nodes.get(self.current, {}).get("title") or ""
                    ).strip(),
                    node_id=self.current,
                    turn=self.state.turn,
                    clues_preview=[
                        self.state.clue_labels.get(k, k)
                        for k in sorted(self.state.clues)
                    ][:6],
                )
            )
            return StepResult(view=self.get_view(), events=[resp.text], is_over=False)

        if action.type != "choose":
            return StepResult(view=self.get_view(), events=["未知動作"], is_over=False)

        view = self.get_view()
        idx = action.choice_index or 0
        if idx <= 0 or idx > len(view.choices):
            return StepResult(view=view, events=["無效選項"], is_over=False)

        # choose 才算一回合
        self.state.turn += 1

        ending_check_node = self._ending_check_node()

        # ----------------------------
        # 0) ending_check injected：回到調查
        # ----------------------------
        if self.current == ending_check_node:
            picked = view.choices[idx - 1]
            tag = (getattr(picked, "tag", "") or "").strip()
            if tag == "ux:back_to_investigate":
                events.append(
                    "霏霏：好，我們先不急著收尾。再回去看看現場，找一個更清楚的小細節。"
                )
                events.append("樂樂：嗯！我們慢慢找，不用急著說名字。")

                target = (self.last_investigate_node or "").strip()
                if target and target in self.nodes:
                    self.current = target
                else:
                    self.current = (
                        self._start_node_id
                        if self._start_node_id in self.nodes
                        else next(iter(self.nodes.keys()))
                    )

                return StepResult(
                    view=self.get_view(),
                    events=events,
                    is_over=False,
                    selected_choice_index=idx,
                    selected_next=self.current,
                    commands=commands,
                )

        # ----------------------------
        # 0.5) Flow nodes：ending_result / ending_wrong / epilogue
        # ----------------------------
        if (
            self._is_ending_result_node(self.current)
            or self._is_ending_wrong_node(self.current)
            or self._is_epilogue_node(self.current)
        ):
            picked = view.choices[idx - 1]
            tag = (getattr(picked, "tag", "") or "").strip()
            if tag.startswith("flow:"):
                flow_action = tag.split(":", 1)[1].strip()

                # flow:go_epilogue 是引擎內部跳轉，不交給 UI
                if flow_action == "go_epilogue":
                    # 你 story node id 叫 "epilogue"
                    if "epilogue" in self.nodes:
                        self.current = "epilogue"
                        return StepResult(
                            view=self.get_view(),
                            events=events,
                            is_over=False,
                            selected_choice_index=idx,
                            selected_next=self.current,
                            commands=commands,
                        )
                    # 沒有 epilogue 就直接當 quit
                    commands.append({"type": "flow", "action": "quit"})
                    return StepResult(
                        view=None, events=events, is_over=True, commands=commands
                    )

                # 其他 flow 交給 CLI/Flutter（restart_case / switch_case / quit）
                commands.append({"type": "flow", "action": flow_action})
                return StepResult(
                    view=None,
                    events=events,
                    is_over=True,  # 讓 UI/CLI 收到 flow 後做重開/換案
                    selected_choice_index=idx,
                    selected_next="",
                    commands=commands,
                )

        # ----------------------------
        # 1) A) 只要現在是 investigate，就更新 last_investigate_node
        # ----------------------------
        if self._is_investigate_node(self.current):
            self.last_investigate_node = self.current

        # ----------------------------
        # 2) story choice（正常流程）
        # ----------------------------
        node = self.nodes[self.current]
        choice = (node.get("choices") or [])[idx - 1]

        self._apply_choice_effects_and_collect_events(choice, events)

        next_id = (choice.get("next") or "").strip()
        if not next_id:
            return StepResult(view=None, events=events + ["故事結束"], is_over=True)

        accuse_node = self._accuse_node()
        reason_node = self._reason_node()
        has_reason = bool(self.state.last_reason_ids)

        # Gate: going to accuse -> ask reason first
        if accuse_node and reason_node and next_id == accuse_node and not has_reason:
            self.current = reason_node
            commands.append(self._make_ask_reason_command())
            return StepResult(
                view=self.get_view(), events=events, is_over=False, commands=commands
            )

        # accuse feedback
        final_next = self._handle_accuse_if_needed(
            current_node=self.current,
            next_id=next_id,
            events=events,
            commands=commands,
        )

        # 進 ending_check 前記住 last_play_node（保留）
        if final_next == ending_check_node:
            self.last_play_node = self.current

        self.current = final_next

        # entering accuse_node: reset reason (new round)
        if accuse_node and self.current == accuse_node:
            self.state.last_reason_id = ""
            self.state.last_reason_text = ""

        return StepResult(
            view=self.get_view(), events=events, is_over=False, commands=commands
        )

    # ----------------------------
    # Save / Load
    # ----------------------------
    def export_snapshot(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "state": self.state.to_dict(),
            "session": {
                "current": self.current,
                "start_node": self._start_node_id,
                "last_play_node": self.last_play_node,
                "last_investigate_node": self.last_investigate_node,
            },
        }


def restore_session_from_snapshot(
    *,
    snapshot: Dict[str, Any],
    nodes: Dict[str, Any],
    config: GameConfig,
    solve_rule: Optional[Dict[str, Any]] = None,
    ai: Optional[AiClient] = None,
) -> GameSession:
    state = DetectiveState.from_dict(snapshot.get("state", {}) or {})
    sess = snapshot.get("session") or {}

    current = str(sess.get("current") or "").strip()
    if not current or current not in nodes:
        current = next(iter(nodes.keys()))

    s = GameSession(
        state=state,
        nodes=nodes,
        start_node=current,
        config=config,
        solve_rule=solve_rule or {},
        ai=ai,
    )

    start_node = str(sess.get("start_node") or "").strip()
    if start_node and start_node in nodes:
        s._start_node_id = start_node

    last_play = str(sess.get("last_play_node") or "").strip()
    if last_play and last_play in nodes:
        s.last_play_node = last_play

    last_inv = str(sess.get("last_investigate_node") or "").strip()
    if last_inv and last_inv in nodes:
        s.last_investigate_node = last_inv

    return s
