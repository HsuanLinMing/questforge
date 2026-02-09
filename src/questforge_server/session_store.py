# src/questforge_server/session_store.py
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, fields
from typing import Any, Dict, Optional, Tuple

from questforge.core.models import DetectiveState, GameConfig
from questforge.engine.case_selector import CaseSelector
from questforge.engine.session import GameSession
from questforge.content.cases import CASES
from questforge.ai.ai_client import build_ai_client
from questforge.ai.story_to_nodes import story_package_to_case

@dataclass
class _StoreItem:
    ts: float
    current: GameSession
    current_case_id: str
    next: GameSession
    next_case_id: str

    # ✅ 每個 case-run 一個 run_id（用來隔離/刪除語音包）
    current_run_id: str
    next_run_id: str

    # ✅ next 的「第一頁 bundle」預生成快取（raw dict）
    next_prefetched_bundle: Optional[Dict[str, Any]] = None


class SessionStore:
    def __init__(self, ttl_seconds: int = 60 * 60) -> None:
        self.ttl_seconds = int(ttl_seconds or 0) or (60 * 60)
        self._items: Dict[str, _StoreItem] = {}

    def _cleanup(self) -> None:
        now = time.time()
        expired = []
        for sid, item in self._items.items():
            if now - item.ts > self.ttl_seconds:
                expired.append(sid)
        for sid in expired:
            self._items.pop(sid, None)

    def get(self, session_id: str) -> Optional[GameSession]:
        self._cleanup()
        sid = (session_id or "").strip()
        if not sid:
            return None
        item = self._items.get(sid)
        if not item:
            return None
        item.ts = time.time()
        return item.current

    def get_next(self, session_id: str) -> Optional[GameSession]:
        self._cleanup()
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return None
        item.ts = time.time()
        return item.next

    def get_case_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return None
        return item.current_case_id

    # ----------------------------
    # run_id / prefetch cache
    # ----------------------------
    def get_current_run_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.current_run_id if item else None

    def get_next_run_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.next_run_id if item else None

    def get_next_prefetched_bundle(self, session_id: str) -> Optional[Dict[str, Any]]:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        return item.next_prefetched_bundle if item else None

    def set_next_prefetched_bundle(self, session_id: str, bundle: Optional[Dict[str, Any]]) -> None:
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return
        item.next_prefetched_bundle = bundle
        item.ts = time.time()

    def delete(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        self._items.pop(sid, None)

    def _build_session(self, case_id: str, seed: int | None = None) -> Tuple[str, GameSession]:
        case = CASES.get(case_id)
        if not case:
            selector = CaseSelector(CASES)
            case_id, case = selector.pick()

        nodes = case.get("nodes") or {}
        start_node = (
            (case.get("start_node") or "").strip()
            or (case.get("start") or "").strip()
            or next(iter(nodes.keys()))
        )
        solve_rule = case.get("solve_rule") or {}

        config_kwargs = {}
        try:
            cfg_fields = {f.name for f in fields(GameConfig)}
            if seed is not None and "seed" in cfg_fields:
                config_kwargs["seed"] = int(seed)
        except Exception:
            pass
        config = GameConfig(**config_kwargs)  # type: ignore[arg-type]

        state = DetectiveState()
        return case_id, GameSession(
            state=state,
            nodes=nodes,
            start_node=start_node,
            config=config,
            solve_rule=solve_rule,
        )

    def _pick_two_cases(self) -> Tuple[str, str]:
        selector = CaseSelector(CASES)
        a, _ = selector.pick()
        b, _ = selector.pick()
        if b == a:
            all_ids = list(CASES.keys())
            candidates = [x for x in all_ids if x != a]
            if candidates:
                b = candidates[int(time.time()) % len(candidates)]
        return a, b

    def create(self, seed: int | None = None) -> Tuple[str, GameSession]:
        self._cleanup()

        case_a, case_b = self._pick_two_cases()
        case_a, sess_a = self._build_session(case_id=case_a, seed=seed)
        case_b, sess_b = self._build_session(case_id=case_b, seed=seed)

        sid = uuid.uuid4().hex
        self._items[sid] = _StoreItem(
            ts=time.time(),
            current=sess_a,
            current_case_id=case_a,
            next=sess_b,
            next_case_id=case_b,
            current_run_id=uuid.uuid4().hex,
            next_run_id=uuid.uuid4().hex,
            next_prefetched_bundle=None,
        )
        return sid, sess_a

    def reset_current(self, session_id: str, case_id: str, seed: int | None = None) -> Tuple[Optional[GameSession], Optional[str]]:
        """重開 current（保留 next 不動）。回傳 (new_session, old_current_run_id_to_delete)"""
        sid = (session_id or "").strip()
        if not sid:
            return None, None
        self._cleanup()
        item = self._items.get(sid)
        if not item:
            return None, None

        old_run = item.current_run_id
        case_id, sess = self._build_session(case_id=case_id, seed=seed)
        item.current = sess
        item.current_case_id = case_id

        # ✅ current 也換一個新的 run_id（避免沿用舊音檔）
        item.current_run_id = uuid.uuid4().hex
        item.ts = time.time()
        return sess, old_run

    # ✅ backward-compatible alias（你 routes_game 目前叫 store.reset）
    def reset(self, session_id: str, case_id: str, seed: int | None = None) -> Tuple[Optional[GameSession], Optional[str]]:
        return self.reset_current(session_id=session_id, case_id=case_id, seed=seed)

    def swap_to_next_and_prefetch(self, session_id: str, seed: int | None = None) -> Tuple[Optional[GameSession], Optional[str]]:
        """把 next 變 current，並立刻生成一個新的 next。回傳 (new_current, old_current_run_id_to_delete)"""
        sid = (session_id or "").strip()
        if not sid:
            return None, None
        self._cleanup()
        item = self._items.get(sid)
        if not item:
            return None, None

        old_run = item.current_run_id

        # promote
        item.current = item.next
        item.current_case_id = item.next_case_id
        item.current_run_id = item.next_run_id  # ✅ run_id 一起 promote

        # new next
        selector = CaseSelector(CASES)
        new_case, _ = selector.pick()
        if new_case == item.current_case_id:
            all_ids = list(CASES.keys())
            candidates = [x for x in all_ids if x != item.current_case_id]
            if candidates:
                new_case = candidates[int(time.time()) % len(candidates)]

        new_case, new_sess = self._build_session(case_id=new_case, seed=seed)
        item.next = new_sess
        item.next_case_id = new_case

        # ✅ new next run_id + 清掉 next 預生成 cache
        item.next_run_id = uuid.uuid4().hex
        item.next_prefetched_bundle = None

        item.ts = time.time()
        return item.current, old_run
    
    def materialize_next_ai_case(self, session_id: str, seed: int | None = None) -> bool:
        """
        生成 AI 案件 nodes，直接替換 item.next 為 AI session
        回傳 True=成功替換
        """
        sid = (session_id or "").strip()
        item = self._items.get(sid)
        if not item:
            return False

        try:
            ai = build_ai_client()
            story = ai.generate_story()

            nodes, start_node, solve_rule, _title = story_package_to_case(story)

            # 用同一套 config/state 建新的 next session（最安全）
            cfg = item.current.config
            st = type(item.current.state)()  # DetectiveState()
            new_next = GameSession(
                state=st,
                nodes=nodes,
                start_node=start_node,
                config=cfg,
                solve_rule=solve_rule,
            )

            item.next = new_next
            item.next_case_id = (story.case_id or "ai").strip() or "ai"
            item.next_prefetched_bundle = None  # 讓 routes_game 重新 prefetch bundle+tts
            item.ts = time.time()
            return True
        except Exception:
            return False
