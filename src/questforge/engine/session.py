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

    Day16-C：
    - ending_result / ending_wrong / epilogue：不再用 NodeView choices
    - 改用 commands: show_end_screen，由 UI/CLI 自己顯示 EndScreen
    - UI/CLI 選完回傳 PlayerAction(type=end_flow, end_action=...)
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

        self._start_node_id: str = start_node

        self.ai: AiClient = ai or build_ai_client()
        self._last_ai_text_by_intent: Dict[str, str] = {}

        self.last_play_node: str = start_node
        self.last_investigate_node: str = start_node

    # ----------------------------
    # Helpers: node ids
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

    def _is_investigate_node(self, node_id: str) -> bool:
        return self._node_tag(node_id) == "investigate"

    def _is_ending_result_node(self, node_id: str) -> bool:
        return self._node_tag(node_id) == "ending_result"

    def _is_ending_wrong_node(self, node_id: str) -> bool:
        return self._node_tag(node_id) == "ending_wrong"

    def _is_epilogue_node(self, node_id: str) -> bool:
        return self._node_tag(node_id) == "epilogue"

    def _is_end_screen_node(self, node_id: str) -> bool:
        return self._node_tag(node_id) in ("ending_result", "ending_wrong", "epilogue")

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
    # View (非 EndScreen 的正常節點才會用到)
    # ----------------------------
    def get_view(self):
        node = self.nodes[self.current]
        title = (node.get("title") or "").strip()
        narration = (node.get("narration") or "").strip()

        # ending_check：追加推理回饋 + 回到調查
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

            choices_raw = node.get("choices") or []
            choices: List[ChoiceView] = []
            for i, c in enumerate(choices_raw, start=1):
                choices.append(
                    ChoiceView(
                        index=i,
                        text=(c.get("text") or "").strip(),
                        enabled=True,
                        reason=(c.get("after") or "").strip() or None,
                        tag="",
                    )
                )

            inv = (self.last_investigate_node or "").strip()
            if inv and inv in self.nodes and inv != self._ending_check_node():
                choices.append(
                    ChoiceView(
                        index=len(choices) + 1,
                        text="回到調查（再看看現場）",
                        enabled=True,
                        reason=None,
                        tag="back_to_investigate",
                    )
                )

            self._last_view_cache = NodeView(
                node_id=self.current,
                title=title,
                narration=narration,
                choices=choices,
            )
            return self._last_view_cache

        # Normal node view
        choices_raw = node.get("choices") or []
        choices: List[ChoiceView] = []
        for i, c in enumerate(choices_raw, start=1):
            choices.append(
                ChoiceView(
                    index=i,
                    text=(c.get("text") or "").strip(),
                    enabled=True,
                    reason=(c.get("after") or "").strip() or None,
                    tag="",
                )
            )

        # ✅ Day17-C：accuse 節點加「回去改理由」（這裡才會生效）
        if (self._accuse_node() or "").strip() == self.current:
            choices.append(
                ChoiceView(
                    index=len(choices) + 1,
                    text="我想回去改一下我的理由（先整理再說）",
                    enabled=True,
                    reason=None,
                    tag="edit_reasons",
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

    @staticmethod
    def _build_reason_summary(selected_obs: List[str], reason_text: str) -> str:
        obs = [x.strip() for x in (selected_obs or []) if x and x.strip()]
        rt = (reason_text or "").strip()

        if obs and rt:
            return "、".join(obs[:3]) + f"（補充：{rt}）"
        if obs:
            return "、".join(obs[:3])
        if rt:
            return rt
        return "我還不太確定，想交給老師一起確認。"

    # ----------------------------
    # Commands: ask reason / end screen
    # ----------------------------
    def _make_ask_reason_command(self) -> Dict[str, Any]:
        mode = getattr(self.config, "reason_input_mode", "choice")
        reason_opts = self.solve_rule.get("reason_options") or []
        return {"type": "ask_reason", "mode": mode, "options": reason_opts}

    def _make_end_screen_command(self, *, node_id: str) -> Dict[str, Any]:
        node = self.nodes.get(node_id, {}) or {}
        title = (node.get("title") or "").strip()
        narration = (node.get("narration") or "").strip()
        lesson = node.get("lesson") or []

        tag = self._node_tag(node_id)

        # ✅ 回顧卡片資料（給 Flutter 用）
        accused = (self.state.last_accuse or "").strip()
        reason_ids = list(self.state.last_reason_ids or [])
        accuse_config = solve_rule_to_accuse_config(self.solve_rule)

        result = AccuseResult(
            target=accused,
            reason_ids=reason_ids,
            reason_id=self.state.last_reason_id,
            reason_text=self.state.last_reason_text,
        )
        fb = evaluate_accuse(accuse_config, result, set(self.state.clues))

        # human-readable labels
        matched_labels = [
            self.state.clue_labels.get(k, k) for k in (fb.matched_evidence or [])
        ]
        missing_labels = [
            self.state.clue_labels.get(k, k) for k in (fb.missing_key_evidence or [])
        ]

        # 你選的「觀察理由」文字（給卡片顯示）
        reason_opts = self.solve_rule.get("reason_options", []) or []
        selected_reason_texts = [
            (opt.get("text") or "").strip()
            for opt in reason_opts
            if (opt.get("id") or "").strip()
            in set([str(x).strip() for x in reason_ids])
        ]
        selected_reason_texts = [t for t in selected_reason_texts if t]

        # ending_result / ending_wrong：有「進入尾聲」
        if tag in ("ending_result", "ending_wrong"):
            options = [
                {"id": "go_epilogue", "text": "進入尾聲"},
            ]
        else:
            options = [
                {"id": "restart_case", "text": "再玩一次這個案件"},
                {"id": "switch_case", "text": "玩下一個案件"},
                {"id": "quit", "text": "離開"},
            ]

        return {
            "type": "show_end_screen",
            "node_id": node_id,
            "tag": tag,
            "title": title,
            "narration": narration,
            "lesson": list(lesson) if isinstance(lesson, list) else [],
            "options": options,
            # ✅ extra meta for UI
            "meta": {
                "case_title": (self.solve_rule.get("title") or "").strip(),  # 沒有就空
                "accused": accused,  # 可能空（不確定）
                "reason_ids": reason_ids,
                "selected_observations": selected_reason_texts,
                "turn": int(getattr(self.state, "turn", 0) or 0),
                "clues_preview": [
                    self.state.clue_labels.get(k, k) for k in sorted(self.state.clues)
                ][:8],
                # 推理回饋（同 ending_check 那套）
                "level": fb.level,
                "score": fb.score,
                "threshold": accuse_config.min_good_score,
                "engine_message": (fb.message or "").strip(),
                "matched_evidence": matched_labels,
                "missing_key_evidence": missing_labels[:6],
                "reason_text": (self.state.last_reason_text or "").strip(),
                "reason_summary": self._build_reason_summary(
                    selected_reason_texts, (self.state.last_reason_text or "").strip()
                ),
            },
        }

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
            events.append(resp.text.strip())

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
        # Day16-C: end_flow
        # ----------------------------
        if action.type == "end_flow":
            act = (action.end_action or "").strip()

            if act == "go_epilogue":
                # 留在 engine 內跳 epilogue（避免 UI 直接改 session.current）
                if "epilogue" in self.nodes:
                    self.current = "epilogue"
                    # 進 epilogue 後也用 command-only endscreen
                    commands.append(self._make_end_screen_command(node_id="epilogue"))
                    return StepResult(
                        view=None, events=events, is_over=True, commands=commands
                    )

                # 沒有 epilogue 就退化成 restart
                commands.append({"type": "flow", "action": "restart_case"})
                return StepResult(
                    view=None, events=events, is_over=True, commands=commands
                )

            if act in ("restart_case", "switch_case", "quit"):
                commands.append({"type": "flow", "action": act})
                return StepResult(
                    view=None, events=events, is_over=True, commands=commands
                )

            return StepResult(view=None, events=["未知 end_action"], is_over=True)

        # ----------------------------
        # set_reasons（Day16-A 已完成）
        # ----------------------------
        if action.type == "set_reasons":
            reason_ids = action.reason_ids or []
            reason_text = (action.reason_text or "").strip()

            self.state.last_reason_ids = list(reason_ids)
            self.state.last_reason_id = ""
            self.state.last_reason_text = reason_text

            reason_opts = self.solve_rule.get("reason_options") or []

            events = []
            seen_any = False
            missing_hints: List[str] = []

            # 1) choice-mode：逐個理由 ack + evidence hints
            for rid in reason_ids:
                opt = next(
                    (
                        o
                        for o in reason_opts
                        if (o.get("id") or "").strip() == str(rid).strip()
                    ),
                    None,
                )
                if not opt:
                    continue

                text = (opt.get("text") or "").strip()
                if not text:
                    continue

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
                    events.append(resp.text.strip())

                expected = [
                    str(x).strip()
                    for x in (opt.get("expected_evidence") or [])
                    if str(x).strip()
                ]
                got = [k for k in expected if k in self.state.clues]
                miss = [k for k in expected if k not in self.state.clues]

                if got:
                    seen_any = True
                    labels = [self.state.clue_labels.get(k, k) for k in got]
                    events.append("霏霏：這個想法有線索支持：" + "、".join(labels))

                if miss:
                    missing_hints.append(self.state.clue_labels.get(miss[0], miss[0]))

            # 2) text-mode：一句話理由
            if reason_text:
                resp = self.say_once(
                    ResponseRequest(
                        intent="acknowledge_reason_text",
                        role="feifei",
                        player_text=reason_text,
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
                    events.append(resp.text.strip())

            # 3) 都沒有（不確定）
            if (not reason_ids) and (not reason_text):
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
                    events.append(resp.text.strip())
            # 4) 有選理由但沒對上線索（補一段反思 + missing hints）
            elif (not seen_any) and (reason_ids):
                resp = self.say_once(
                    ResponseRequest(
                        intent="reflect_reasoning",
                        role="feifei",
                        selected_observations=[
                            (opt.get("text") or "").strip()
                            for opt in reason_opts
                            if (opt.get("id") or "").strip()
                            in [str(x).strip() for x in reason_ids]
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
                    events.append(resp.text.strip())
                if missing_hints:
                    labels = "、".join(missing_hints[:2])
                    events.append(f"霏霏：之後可以再留意看看：{labels}")

            # 5) 不確定（交給老師）：直接去 ending_check（不要再逼指認）
            if (not reason_ids) and (not reason_text):
                events.append("霏霏：好，我們先交給老師。你已經做得很棒了。")
                self.current = self._ending_check_node()
                return StepResult(
                    view=self.get_view(),
                    events=events,
                    is_over=False,
                    commands=commands,
                )

            # 6) 有理由：才回到 accuse
            accuse_node = (self._accuse_node() or "accuse").strip()
            self.current = (
                accuse_node
                if accuse_node in self.nodes
                else next(iter(self.nodes.keys()))
            )
            return StepResult(
                view=self.get_view(), events=events, is_over=False, commands=commands
            )

        # ----------------------------
        # basic actions
        # ----------------------------
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

        self.state.turn += 1

        ending_check_node = self._ending_check_node()

        # ending_check injected：回到調查
        if self.current == ending_check_node:
            picked = view.choices[idx - 1]
            if (picked.tag or "").strip() == "back_to_investigate":
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
                    commands=commands,
                )

        # 記錄最後調查點
        if self._is_investigate_node(self.current):
            self.last_investigate_node = self.current

        # ✅ Day17-C：accuse 節點的「回去改理由」
        if self.current == (self._accuse_node() or "").strip():
            picked = view.choices[idx - 1]
            if (picked.tag or "").strip() == "edit_reasons":
                events.append("霏霏：好呀！我們先把理由整理清楚，再慢慢想。")
                # 回 reason_node，並重新 ask_reason
                reason_node = (self._reason_node() or "").strip()
                if reason_node and reason_node in self.nodes:
                    self.current = reason_node
                commands.append(self._make_ask_reason_command())
                return StepResult(
                    view=self.get_view(),
                    events=events,
                    is_over=False,
                    commands=commands,
                )

        # story choice
        node = self.nodes[self.current]
        choice = (node.get("choices") or [])[idx - 1]

        self._apply_choice_effects_and_collect_events(choice, events)

        next_id = (choice.get("next") or "").strip()
        if not next_id:
            return StepResult(view=None, events=events + ["故事結束"], is_over=True)

        accuse_node = self._accuse_node()
        reason_node = self._reason_node()
        has_reason = bool(self.state.last_reason_ids) or bool(
            (self.state.last_reason_text or "").strip()
        )

        # Gate: going to accuse -> ask reason first
        if accuse_node and reason_node and next_id == accuse_node and not has_reason:
            self.current = reason_node
            commands.append(self._make_ask_reason_command())
            return StepResult(
                view=self.get_view(), events=events, is_over=False, commands=commands
            )

        final_next = self._handle_accuse_if_needed(
            current_node=self.current,
            next_id=next_id,
            events=events,
            commands=commands,
        )

        if final_next == ending_check_node:
            self.last_play_node = self.current

        self.current = final_next

        if accuse_node and self.current == accuse_node:
            self.state.last_reason_id = ""
            self.state.last_reason_text = ""

        # ✅ Day16-C：一旦「進入 EndScreen 節點」，回傳 command-only
        if self._is_end_screen_node(self.current):
            commands.append(self._make_end_screen_command(node_id=self.current))
            return StepResult(view=None, events=events, is_over=True, commands=commands)

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
