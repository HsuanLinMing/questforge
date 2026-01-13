# src/questforge/engine/session.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from questforge.core.contracts.reasoning_contract_v1 import ensure_reasoning_contract_v1
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

    def _is_end_screen_node(self, node_id: str) -> bool:
        return self._node_tag(node_id) in ("ending_result", "ending_wrong", "epilogue")

    # ----------------------------
    # Helpers: reason mode + config validation
    # ----------------------------
    def _reason_mode(self) -> str:
        """
        Day18-D1: 每案 solve_rule 可覆蓋輸入模式
          1) solve_rule.reason_mode
          2) config.reason_input_mode
          3) default: "choice"
        """
        mode = (
            self.solve_rule.get("reason_mode")
            or getattr(self.config, "reason_input_mode", None)
            or "choice"
        )
        mode = str(mode).strip().lower()
        if mode not in ("choice", "text", "voice"):
            mode = "choice"
        # voice 先保留 enum，但 engine 目前先當作 text（未來接語音再改）
        if mode == "voice":
            mode = "text"
        return mode

    def _reason_options(self) -> List[Dict[str, Any]]:
        opts = self.solve_rule.get("reason_options") or []
        if isinstance(opts, list):
            return [x for x in opts if isinstance(x, dict)]
        return []

    def _has_reason_input(self) -> bool:
        return bool(self.state.last_reason_ids) or bool(
            (self.state.last_reason_text or "").strip()
        )

    def _safe_has_choice_options(self) -> bool:
        """
        choice-mode 必須要有 reason_options 才能問。
        沒有就視為不可問（避免卡住）。
        """
        if self._reason_mode() != "choice":
            return True
        return len(self._reason_options()) > 0

    def _safe_has_reason_node(self) -> bool:
        rn = (self._reason_node() or "").strip()
        return bool(rn) and rn in self.nodes

    def _safe_has_accuse_node(self) -> bool:
        an = (self._accuse_node() or "").strip()
        return bool(an) and an in self.nodes

    def _should_gate_to_reason(
        self,
        *,
        current_node: str,
        next_id: str,
    ) -> bool:
        """
        Day18-D2: reason gate 策略
        - 只要 next 是 accuse_node 且還沒有理由，就先去 reason_node
        - 即使 choice-mode 缺 reason_options，也要 gate（ask_reason 會自動退化成 text-mode）
        """
        accuse_node = (self._accuse_node() or "").strip()
        if not accuse_node:
            return False
        if next_id != accuse_node:
            return False
        if self._has_reason_input():
            return False

        # 必須存在 reason_node
        if not self._safe_has_reason_node():
            return False

        # ✅ 不再要求 choice-mode 一定要有 options
        #    （缺 options 時 ask_reason 會 fallback 成 text-mode）
        return True

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
    # View
    # ----------------------------
    def get_view(self):
        node = self.nodes[self.current]
        title = (node.get("title") or "").strip()
        narration = (node.get("narration") or "").strip()

        # ending_check：追加推理回饋 + 回到調查
        if self.current == self._ending_check_node():
            narration = self._normalize_duo_narration(narration)

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

        # accuse 節點加「回去改理由」
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

    def _make_reasoning_feedback_command(
        self, *, node_id: str, scene_title: str
    ) -> Dict[str, Any]:
        accuse_config = solve_rule_to_accuse_config(self.solve_rule)

        accused = (self.state.last_accuse or "").strip()
        reason_ids = list(self.state.last_reason_ids or [])
        reason_opts = self.solve_rule.get("reason_options", []) or []

        selected_reason_texts = [
            (opt.get("text") or "").strip()
            for opt in reason_opts
            if (opt.get("id") or "").strip()
            in set([str(x).strip() for x in reason_ids])
        ]
        selected_reason_texts = [t for t in selected_reason_texts if t]

        result = AccuseResult(
            target=accused,
            reason_ids=reason_ids,
            reason_id=self.state.last_reason_id,
            reason_text=self.state.last_reason_text,
        )
        fb = evaluate_accuse(accuse_config, result, set(self.state.clues))

        matched_labels = [
            self.state.clue_labels.get(k, k) for k in (fb.matched_evidence or [])
        ]
        missing_labels = [
            self.state.clue_labels.get(k, k) for k in (fb.missing_key_evidence or [])
        ]

        threshold = accuse_config.min_good_score

        # AI（短句）
        ai_resp = self.say_once(
            ResponseRequest(
                intent="ending_feedback",
                role="teacher",
                scene_title=(scene_title or "").strip(),
                node_id=(node_id or "").strip(),
                turn=self.state.turn,
                clues_preview=[
                    self.state.clue_labels.get(k, k)
                    for k in sorted(list(self.state.clues))[:6]
                ],
                meta={
                    "level": fb.level,
                    "score": fb.score,
                    "threshold": threshold,
                    "matched_evidence": matched_labels,
                    "missing_key_evidence": missing_labels[:6],
                    "engine_message": (fb.message or "").strip(),
                },
            )
        )
        feedback_text = (
            ai_resp.text.strip() if ai_resp.text.strip() else "我們慢慢來就好。"
        )

        raw_meta = {
            "case_title": (self.solve_rule.get("title") or "").strip(),
            "node_id": (node_id or "").strip(),
            "tag": "ending_check",
            "turn": int(getattr(self.state, "turn", 0) or 0),
            "accused": accused,
            "reason_mode": self._reason_mode(),
            "reason_ids": reason_ids,
            "selected_observations": selected_reason_texts,
            "reason_text": (self.state.last_reason_text or "").strip(),
            "reason_summary": self._build_reason_summary(
                selected_reason_texts, (self.state.last_reason_text or "").strip()
            ),
            "clues_preview": [
                self.state.clue_labels.get(k, k) for k in sorted(self.state.clues)
            ][:8],
            "level": fb.level,
            "score": fb.score,
            "threshold": threshold,
            "engine_message": (fb.message or "").strip(),
            "matched_evidence": matched_labels,
            "missing_key_evidence": missing_labels[:6],
        }

        return {
            "type": "show_reasoning_feedback",
            "text": feedback_text,
            "meta": ensure_reasoning_contract_v1(raw_meta),
        }

    def _make_ask_reason_command(self) -> Dict[str, Any]:
        """
        Day18-D4: ask_reason payload 正式化（Flutter/CLI 都能直接畫 UI）
        """
        mode = self._reason_mode()
        opts = self._reason_options()

        title = (self.solve_rule.get("reason_title") or "【你為什麼這樣想？】").strip()
        hint = (
            self.solve_rule.get("reason_hint")
            or "提示：只要講『你看到的』就好，不用猜誰做的。"
        ).strip()
        max_len = int(self.solve_rule.get("reason_max_len", 80) or 80)
        if max_len <= 0:
            max_len = 80
        if max_len > 200:
            max_len = 200

        # choice-mode 沒 options：退化成 text-mode（避免卡住）
        if mode == "choice" and not opts:
            mode = "text"

        return {
            "type": "ask_reason",
            "mode": mode,  # "choice" | "text" (voice 目前會被轉成 text)
            "options": opts,  # choice-mode 才用得到
            "title": title,
            "hint": hint,
            "max_len": max_len,
        }

    def _make_end_screen_command(self, *, node_id: str) -> Dict[str, Any]:
        node = self.nodes.get(node_id, {}) or {}
        title = (node.get("title") or "").strip()
        narration = (node.get("narration") or "").strip()
        lesson = node.get("lesson") or []

        tag = self._node_tag(node_id)

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

        matched_labels = [
            self.state.clue_labels.get(k, k) for k in (fb.matched_evidence or [])
        ]
        missing_labels = [
            self.state.clue_labels.get(k, k) for k in (fb.missing_key_evidence or [])
        ]

        reason_opts = self.solve_rule.get("reason_options", []) or []
        selected_reason_texts = [
            (opt.get("text") or "").strip()
            for opt in reason_opts
            if (opt.get("id") or "").strip()
            in set([str(x).strip() for x in reason_ids])
        ]
        selected_reason_texts = [t for t in selected_reason_texts if t]

        if tag in ("ending_result", "ending_wrong"):
            options = [{"id": "go_epilogue", "text": "進入尾聲"}]
        else:
            options = [
                {"id": "restart_case", "text": "再玩一次這個案件"},
                {"id": "switch_case", "text": "玩下一個案件"},
                {"id": "quit", "text": "離開"},
            ]

        raw_meta = {
            "case_title": (self.solve_rule.get("title") or "").strip(),
            "node_id": node_id,
            "tag": tag,
            "accused": accused,
            "reason_mode": self._reason_mode(),
            "reason_ids": reason_ids,
            "selected_observations": selected_reason_texts,
            "turn": int(getattr(self.state, "turn", 0) or 0),
            "clues_preview": [
                self.state.clue_labels.get(k, k) for k in sorted(self.state.clues)
            ][:8],
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
        }

        return {
            "type": "show_end_screen",
            "node_id": node_id,
            "tag": tag,
            "title": title,
            "narration": narration,
            "lesson": list(lesson) if isinstance(lesson, list) else [],
            "options": options,
            "meta": ensure_reasoning_contract_v1(raw_meta),
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
                if "epilogue" in self.nodes:
                    self.current = "epilogue"
                    commands.append(self._make_end_screen_command(node_id="epilogue"))
                    return StepResult(
                        view=None, events=events, is_over=True, commands=commands
                    )

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
        # set_reasons
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

                # 5) 不確定：直接去 ending_check（不再逼指認）
                if (not reason_ids) and (not reason_text):
                    events.append("霏霏：好，我們先交給老師。你已經做得很棒了。")
                    self.current = self._ending_check_node()

                    # ✅ Day19-D：即使是 set_reasons 導向 ending_check，也要發 feedback command
                    ending_check_node = (self._ending_check_node() or "").strip()
                    if ending_check_node and self.current == ending_check_node:
                        scene_title = (
                            self.nodes.get(self.current, {}).get("title") or ""
                        ).strip()
                        commands.append(
                            self._make_reasoning_feedback_command(
                                node_id=self.current, scene_title=scene_title
                            )
                        )

                    return StepResult(
                        view=self.get_view(),
                        events=events,
                        is_over=False,
                        commands=commands,
                    )

            # 6) 有理由：回 accuse
            accuse_node = (self._accuse_node() or "accuse").strip()

            # Day18-C：整理理由後，清掉上一次指認（避免 stale）
            self.state.last_accuse = ""

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

        # accuse 節點的「回去改理由」
        if self.current == (self._accuse_node() or "").strip():
            picked = view.choices[idx - 1]
            if (picked.tag or "").strip() == "edit_reasons":
                events.append("霏霏：好呀！我們先把理由整理清楚，再慢慢想。")
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

        # Day18-D2: gate（只有在配置完整時才 gate）
        if self._should_gate_to_reason(current_node=self.current, next_id=next_id):
            # 進入 reason 前先清 accuse（避免殘留）
            self.state.last_accuse = ""
            self.current = self._reason_node()
            commands.append(self._make_ask_reason_command())
            return StepResult(
                view=self.get_view(), events=events, is_over=False, commands=commands
            )

        # accuse feedback（進 ending_check）
        final_next = self._handle_accuse_if_needed(
            current_node=self.current,
            next_id=next_id,
            events=events,
            commands=commands,
        )

        self.current = final_next

        # ✅ Day19-D：進 ending_check 就發 reasoning_feedback command（用 command 顯示，不塞 narration）
        ending_check_node = (self._ending_check_node() or "").strip()
        if ending_check_node and self.current == ending_check_node:
            scene_title = (self.nodes.get(self.current, {}).get("title") or "").strip()
            commands.append(
                self._make_reasoning_feedback_command(
                    node_id=self.current, scene_title=scene_title
                )
            )
            return StepResult(
                view=self.get_view(),
                events=events,
                is_over=False,
                commands=commands,
            )

        # Day18-D2（補強）：如果「走到 reason_node」且需要理由，才出 ask_reason
        # 但要避免缺配置卡住：choice-mode 沒 options 會自動退化成 text-mode
        rn = (self._reason_node() or "").strip()
        if rn and self.current == rn and (not self._has_reason_input()):
            commands.append(self._make_ask_reason_command())
            return StepResult(
                view=self.get_view(), events=events, is_over=False, commands=commands
            )

        # EndScreen command-only
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
