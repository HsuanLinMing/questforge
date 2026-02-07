# src/questforge/engine/session.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from questforge.core.contracts.reasoning_contract_v1 import ensure_reasoning_contract_v1
from questforge.ai.ai_client import AiClient, build_ai_client
from questforge.ai.guard_log import log_guard_result
from questforge.ai.response_guard import guard_response
from questforge.ai.schemas import ResponsePackage, ResponseRequest, StoryPackage
from questforge.core.models import AccuseResult, DetectiveState, GameConfig
from questforge.engine.actions import PlayerAction
from questforge.engine.effects import apply_effects
from questforge.engine.reasoning import evaluate_accuse
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
    """純邏輯遊戲流程控制器（不做 print/input）。"""

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

        s = (start_node or "").strip()
        if (not s) or (s not in self.nodes):
            s = next(iter(self.nodes.keys()))
        self.current = s

        self.config = config
        self.solve_rule = solve_rule or {}
        self._last_view_cache = None

        self._start_node_id = s

        self.ai: AiClient = ai or build_ai_client()
        self._last_ai_text_by_intent: Dict[str, str] = {}

        self.last_play_node = s
        self.last_investigate_node = s

    # ----------------------------
    # Helpers: node ids
    # ----------------------------
    def _coerce_valid_node(self, node_id: str) -> str:
        nid = (node_id or "").strip()
        if nid and nid in self.nodes:
            return nid

        inv = (self.last_investigate_node or "").strip()
        if inv and inv in self.nodes:
            return inv

        s = (self._start_node_id or "").strip()
        if s and s in self.nodes:
            return s

        return next(iter(self.nodes.keys()))

    def _resolve_node_id(self, configured: str, candidates: list[str]) -> str:
        cid = (configured or "").strip()
        if cid and cid in self.nodes:
            return cid
        for x in candidates:
            xid = (x or "").strip()
            if xid and xid in self.nodes:
                return xid
        return ""

    def _reason_node(self) -> str:
        configured = (self.solve_rule.get("reason_node") or "").strip()
        return self._resolve_node_id(configured, ["mid_reason", "reason"])

    def _accuse_node(self) -> str:
        configured = (self.solve_rule.get("accuse_node") or "").strip()
        return self._resolve_node_id(configured, ["final_accuse", "accuse"])

    def _ending_check_node(self) -> str:
        configured = (self.solve_rule.get("ending_check_node") or "").strip()
        return self._resolve_node_id(configured, ["ending_check"])

    # ✅ tri endings
    def _ending_clear_node(self) -> str:
        configured = (self.solve_rule.get("ending_clear_node") or "").strip()
        return self._resolve_node_id(
            configured, ["scene_10_ending_clear", "ending_result"]
        )

    def _ending_nudge_node(self) -> str:
        configured = (self.solve_rule.get("ending_nudge_node") or "").strip()
        return self._resolve_node_id(configured, ["scene_10_ending_nudge"])

    def _ending_defer_node(self) -> str:
        configured = (self.solve_rule.get("ending_defer_node") or "").strip()
        return self._resolve_node_id(
            configured, ["scene_10_ending_defer", "epilogue", "quit"]
        )

    def _fallback_after_accuse(self) -> str:
        if "epilogue" in self.nodes:
            return "epilogue"
        if "quit" in self.nodes:
            return "quit"
        return self._coerce_valid_node("")

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
        end_screen_node = (self.solve_rule.get("end_screen_node") or "").strip()
        if end_screen_node:
            return node_id == end_screen_node

        tag = self._node_tag(node_id)
        if tag in ("ending_result", "ending_wrong", "epilogue", "quit", "end_screen"):
            return True

        nid = (node_id or "").lower().strip()
        if nid.startswith("ending_"):
            return True
        if nid.startswith("epilogue"):
            return True
        if nid == "quit":
            return True
        return False

    # ----------------------------
    # Reason input helpers
    # ----------------------------
    def _reason_mode(self) -> str:
        mode = (
            self.solve_rule.get("reason_mode")
            or getattr(self.config, "reason_input_mode", None)
            or "choice"
        )
        mode = str(mode).strip().lower()
        if mode not in ("choice", "text", "voice"):
            mode = "choice"
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

    def _should_gate_to_reason(self, *, current_node: str, next_id: str) -> bool:
        accuse_node = (self._accuse_node() or "").strip()
        if not accuse_node:
            return False
        if next_id != accuse_node:
            return False
        if self._has_reason_input():
            return False

        rn = (self._reason_node() or "").strip()
        if not rn or rn not in self.nodes:
            return False

        first_interaction = (self.solve_rule.get("first_interaction_node") or "").strip()
        if first_interaction and rn == first_interaction:
            return False

        if (self._start_node_id or "").strip() and rn == (self._start_node_id or "").strip():
            return False

        return True

    # ----------------------------
    # tri-ending availability
    # ----------------------------
    def _has_tri_endings(self) -> bool:
        a = (self._ending_clear_node() or "").strip()
        b = (self._ending_nudge_node() or "").strip()
        c = (self._ending_defer_node() or "").strip()
        return bool(a and b and c and a in self.nodes and b in self.nodes and c in self.nodes)

    # ----------------------------
    # ✅ A 方案：final_accuse 路由（用 solution_index）
    # ----------------------------
    def _use_solution_index(self) -> bool:
        return bool(self.solve_rule.get("use_solution_index", False))

    def _route_after_final_accuse_A(self, *, choice_index_1based: int) -> str:
        """
        A 方案：
        - 第4個選項（不確定/交給老師）=> defer
        - 前3個：用 solution_index (0/1/2) 判斷 clear / nudge
        - 任何異常/缺欄位：保守 defer
        """
        defer_node = (self._ending_defer_node() or "").strip() or self._fallback_after_accuse()
        clear_node = (self._ending_clear_node() or "").strip() or self._fallback_after_accuse()
        nudge_node = (self._ending_nudge_node() or "").strip() or defer_node

        if not self._has_tri_endings():
            ending_check = (self._ending_check_node() or "").strip()
            if ending_check and ending_check in self.nodes:
                return ending_check
            return self._fallback_after_accuse()

        if choice_index_1based == 4:
            return defer_node

        if choice_index_1based < 1 or choice_index_1based > 3:
            return defer_node

        accuse_node_id = (self._accuse_node() or "").strip()
        node = self.nodes.get(accuse_node_id, {}) or {}
        sol = node.get("solution_index", None)

        try:
            sol_idx = int(sol) if sol is not None else -1
        except Exception:
            sol_idx = -1

        if sol_idx not in (0, 1, 2):
            return defer_node

        picked0 = choice_index_1based - 1
        if picked0 == sol_idx:
            return clear_node
        return nudge_node

    # ----------------------------
    # (Optional) 舊 tri-endings：support/clues 評分（保留相容）
    # ----------------------------
    @staticmethod
    def _to_float(x: Any, default: float = 0.0) -> float:
        try:
            return float(x)
        except Exception:
            return default

    def _tri_threshold(self) -> float:
        accuse_config = solve_rule_to_accuse_config(self.solve_rule)
        t = self.solve_rule.get("threshold", None)
        if t is None or t == "":
            t = getattr(accuse_config, "min_good_score", 0)
        return self._to_float(t, 0.0)

    def _tri_margin(self, threshold: float) -> float:
        m = self.solve_rule.get("ending_nudge_margin", None)
        if m is None or m == "":
            return 0.15 if threshold <= 1.0 else 1.0
        return self._to_float(m, 0.0)

    def _tri_pick_ending(self, score: float, threshold: float, margin: float) -> str:
        clear_node = (self._ending_clear_node() or "").strip()
        nudge_node = (self._ending_nudge_node() or "").strip()
        defer_node = (self._ending_defer_node() or "").strip()

        if threshold <= 0:
            return clear_node or defer_node or self._fallback_after_accuse()

        if score >= threshold:
            return clear_node or self._fallback_after_accuse()

        if margin > 0 and score >= (threshold - margin):
            return nudge_node or defer_node or self._fallback_after_accuse()

        return defer_node or self._fallback_after_accuse()

    def _score_by_clues_support(self, *, target: str) -> float:
        """
        suspects[target].support: { clue_key: weight }
        score = sum(weight for clue_key in clues if present)
        """
        if not target:
            return 0.0

        suspects = self.solve_rule.get("suspects", {}) or {}
        profile = suspects.get(target, {}) or {}
        support = profile.get("support", {}) or {}
        if (not isinstance(support, dict)) or (not support):
            return 0.0

        clues = set(self.state.clues or [])
        total = 0.0
        for k, w in support.items():
            kk = str(k or "").strip()
            if not kk:
                continue
            if kk in clues:
                total += self._to_float(w, 0.0)
        return float(total)

    def _handle_accuse_if_needed_legacy(self, *, current_node: str, next_id: str) -> str:
        accuse_node = (self._accuse_node() or "").strip()
        if not accuse_node or current_node != accuse_node:
            return next_id

        # tri-endings
        if self._has_tri_endings():
            chosen = (self.state.last_accuse or "").strip()
            if not chosen:
                return (self._ending_defer_node() or "").strip() or self._fallback_after_accuse()

            threshold = self._tri_threshold()
            margin = self._tri_margin(threshold)

            score = self._score_by_clues_support(target=chosen)
            if score <= 0.0:
                return (self._ending_defer_node() or "").strip() or self._fallback_after_accuse()

            return self._tri_pick_ending(score, threshold, margin)

        # old ending_check
        ending_check = (self._ending_check_node() or "").strip()
        if ending_check and ending_check in self.nodes:
            return ending_check

        return next_id

    # ----------------------------
    # AI
    # ----------------------------
    def generate_new_case(self) -> StoryPackage:
        return self.ai.generate_story()

    def say(self, req: ResponseRequest) -> ResponsePackage:
        try:
            if not getattr(req, "scene_title", ""):
                req.scene_title = (self.nodes.get(self.current, {}).get("title") or "").strip()
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
    # View
    # ----------------------------
    @staticmethod
    def _beats_to_narration(beats: Any) -> str:
        if not isinstance(beats, list):
            return ""
        lines: List[str] = []
        for b in beats:
            if not isinstance(b, dict):
                continue
            sp = (b.get("speaker") or "").strip()
            tx = (b.get("text") or "").strip()
            if not tx:
                continue
            if sp:
                lines.append(f"{sp}：{tx}")
            else:
                lines.append(tx)
        return "\n\n".join(lines)

    def get_view(self):
        node = self.nodes[self.current]
        title = (node.get("title") or "").strip()

        narration = (node.get("narration") or "").strip()
        if not narration:
            narration = self._beats_to_narration(node.get("beats"))

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

        # accuse 節點加「回去改理由」：只有在 reason_node 存在時才加
        if (self._accuse_node() or "").strip() == self.current:
            rn = (self._reason_node() or "").strip()
            if rn and rn in self.nodes:
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

    # ----------------------------
    # Commands: ask_reason / end screen
    # ----------------------------
    def _make_ask_reason_command(self) -> Dict[str, Any]:
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

        if mode == "choice" and not opts:
            mode = "text"

        return {
            "type": "ask_reason",
            "mode": mode,
            "options": opts,
            "title": title,
            "hint": hint,
            "max_len": max_len,
        }

    def _make_end_screen_command(self, *, node_id: str) -> Dict[str, Any]:
        node = self.nodes.get(node_id, {}) or {}
        title = (node.get("title") or "").strip()

        narration = (node.get("narration") or "").strip()
        if not narration:
            narration = self._beats_to_narration(node.get("beats"))

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
            "turn": int(getattr(self.state, "turn", 0) or 0),
            "level": fb.level,
            "score": fb.score,
            "threshold": getattr(accuse_config, "min_good_score", 0),
            "engine_message": (fb.message or "").strip(),
            "reason_text": (self.state.last_reason_text or "").strip(),
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
    # Accuse helper: map choice index -> suspect id (legacy)
    # ----------------------------
    def _apply_accuse_choice_if_needed(self, *, node_id: str, choice_index: int) -> None:
        accuse_node = (self._accuse_node() or "").strip()
        if not accuse_node or node_id != accuse_node:
            return

        # 第4個選項是不確定：不要當 accused
        if choice_index == 4:
            self.state.last_accuse = ""
            return

        mapping = self.solve_rule.get("accuse_choice_to_suspect") or {}
        sid = str(mapping.get(str(choice_index), "")).strip()
        if not sid:
            try:
                node = self.nodes.get(node_id, {}) or {}
                choices = node.get("choices") or []
                if 0 < choice_index <= len(choices):
                    sid = str((choices[choice_index - 1].get("text") or "")).strip()
            except Exception:
                sid = ""

        self.state.last_accuse = sid

    # ----------------------------
    # Internal: apply choice effects
    # ----------------------------
    def _apply_choice_effects_and_collect_events(self, choice: Dict[str, Any], events: List[str]) -> None:
        apply_effects(self.state, choice.get("effects"))

        for ev in choice.get("evidence") or []:
            try:
                self.state.add_clue_with_label(ev.get("key", ""), ev.get("label"))
            except Exception:
                pass

        after = (choice.get("after") or "").strip()
        if after:
            events.append(after)

        if "accuse" in choice:
            self.state.last_accuse = (choice.get("accuse") or "").strip()

    # ----------------------------
    # Step
    # ----------------------------
    def step(self, action: PlayerAction) -> StepResult:
        events: List[str] = []
        commands: List[Dict[str, Any]] = []

        # end_flow
        if action.type == "end_flow":
            act = (action.end_action or "").strip()

            if act == "go_epilogue":
                if "epilogue" in self.nodes:
                    self.current = "epilogue"
                    commands.append(self._make_end_screen_command(node_id="epilogue"))
                    return StepResult(view=None, events=events, is_over=True, commands=commands)
                return StepResult(view=None, events=["沒有 epilogue 節點"], is_over=True, commands=[])

            if act in ("restart_case", "switch_case", "quit"):
                return StepResult(view=None, events=events, is_over=True, commands=[])

            return StepResult(view=None, events=["未知 end_action"], is_over=True)

        # set_reasons
        if action.type == "set_reasons":
            reason_ids = action.reason_ids or []
            reason_text = (action.reason_text or "").strip()

            self.state.last_reason_ids = list(reason_ids)
            self.state.last_reason_id = ""
            self.state.last_reason_text = reason_text

            try:
                resp = self.say_once(
                    ResponseRequest(
                        intent="ack_reasons_simple",
                        role="feifei",
                        node_id=self.current,
                        turn=self.state.turn,
                        scene_title=(self.nodes.get(self.current, {}).get("title") or "").strip(),
                        meta={"has_choice": bool(reason_ids), "has_text": bool(reason_text)},
                    )
                )
                if resp.text.strip():
                    events.append(resp.text.strip())
            except Exception:
                pass

            accuse_node = (self._accuse_node() or "accuse").strip()
            self.state.last_accuse = ""
            self.current = accuse_node if accuse_node in self.nodes else next(iter(self.nodes.keys()))
            return StepResult(view=self.get_view(), events=events, is_over=False, commands=commands)

        # confirm_quiz_answer
        if action.type == "confirm_quiz_answer":
            answers = action.answers or []
            skipped = bool(getattr(action, "skipped", False))

            try:
                self.state.last_confirm_quiz_answers = list(answers)
                self.state.last_confirm_quiz_skipped = bool(skipped)
            except Exception:
                pass

            events.append("霏霏：好，我們往下看看。")

            if "epilogue" in self.nodes:
                self.current = "epilogue"
                commands.append(self._make_end_screen_command(node_id="epilogue"))
                return StepResult(view=None, events=events, is_over=True, commands=commands)

            commands.append({"type": "flow", "action": "restart_case"})
            return StepResult(view=None, events=events, is_over=True, commands=commands)

        # basic actions
        if action.type == "quit":
            return StepResult(view=None, events=["玩家選擇離開"], is_over=True)

        if action.type == "replay":
            resp = self.say_once(
                ResponseRequest(
                    intent="replay_context",
                    role="feifei",
                    scene_title=(self.nodes.get(self.current, {}).get("title") or "").strip(),
                    node_id=self.current,
                    turn=self.state.turn,
                )
            )
            return StepResult(view=self.get_view(), events=[resp.text], is_over=False)

        if action.type != "choose":
            return StepResult(view=self.get_view(), events=["未知動作"], is_over=False)

        view = self.get_view()
        idx = int(action.choice_index or 0)
        if idx <= 0 or idx > len(view.choices):
            return StepResult(view=view, events=["無效選項"], is_over=False)

        # turn + 1（不要寫死 1）
        try:
            self.state.turn = int(getattr(self.state, "turn", 0) or 0) + 1
        except Exception:
            self.state.turn = 1

        # 記錄最後調查點
        if self._is_investigate_node(self.current):
            self.last_investigate_node = self.current

        accuse_node_id = (self._accuse_node() or "").strip()

        # accuse node: edit reasons
        if self.current == accuse_node_id:
            picked = view.choices[idx - 1]
            if (picked.tag or "").strip() == "edit_reasons":
                events.append("霏霏：好呀！我們先把理由整理清楚，再慢慢想。")
                reason_node = (self._reason_node() or "").strip()
                if reason_node and reason_node in self.nodes:
                    self.current = reason_node
                    commands.append(self._make_ask_reason_command())
                    return StepResult(view=self.get_view(), events=events, is_over=False, commands=commands)

        # ✅ A方案：final_accuse 選完直接導去 ending（不靠 choice.next）
        if self.current == accuse_node_id and self._use_solution_index():
            # 讓 end screen meta 可以看到 accused（第4個會清空）
            self._apply_accuse_choice_if_needed(node_id=self.current, choice_index=idx)

            final_next = self._route_after_final_accuse_A(choice_index_1based=idx)
            self.current = self._coerce_valid_node(final_next)

            if self._is_end_screen_node(self.current):
                commands.append(self._make_end_screen_command(node_id=self.current))
                return StepResult(view=None, events=events, is_over=True, commands=commands)

            return StepResult(view=self.get_view(), events=events, is_over=False, commands=commands)

        # ----------------------------
        # 一般 story scene：照 story choice.next 前進
        # ----------------------------
        node = self.nodes[self.current]
        choices_raw = node.get("choices") or []
        choice = choices_raw[idx - 1] if 0 < idx <= len(choices_raw) else {}

        # legacy：如果在 accuse_node 但沒開 A 方案，仍可先記 accused（給 tri/support 用）
        if self.current == accuse_node_id and not self._use_solution_index():
            self._apply_accuse_choice_if_needed(node_id=self.current, choice_index=idx)

        self._apply_choice_effects_and_collect_events(choice, events)

        next_id = (choice.get("next") or "").strip()
        if not next_id:
            return StepResult(view=None, events=events + ["故事結束"], is_over=True)

        # gate to reason（版本S reason_node 空，會自然不 gate）
        if self._should_gate_to_reason(current_node=self.current, next_id=next_id):
            self.state.last_accuse = ""
            self.current = self._reason_node()
            commands.append(self._make_ask_reason_command())
            return StepResult(view=self.get_view(), events=events, is_over=False, commands=commands)

        # legacy accuse handling（tri/support / ending_check）
        final_next = self._handle_accuse_if_needed_legacy(current_node=self.current, next_id=next_id)
        self.current = self._coerce_valid_node(final_next)

        rn = (self._reason_node() or "").strip()
        if rn and self.current == rn and (not self._has_reason_input()):
            commands.append(self._make_ask_reason_command())
            return StepResult(view=self.get_view(), events=events, is_over=False, commands=commands)

        if self._is_end_screen_node(self.current):
            commands.append(self._make_end_screen_command(node_id=self.current))
            return StepResult(view=None, events=events, is_over=True, commands=commands)

        return StepResult(view=self.get_view(), events=events, is_over=False, commands=commands)

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
